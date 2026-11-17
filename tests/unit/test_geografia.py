"""Geografia da vaga (país, UF, região, cidade) e parte de local das chaves de deduplicação."""
import pytest

from jobradar.transformations.geografia import chave_local, chave_remota, localizar
from jobradar.transformations.silver import chave_alternativa
from jobradar.transformations.text import normalizar, sha1
from jobradar.transformations.silver import RUIDO_TITULO


@pytest.mark.parametrize("country,state,city,local,esperado", [
    # (pais_iso, uf, cidade_norm, origem)
    ("Brasil", "São Paulo", "São Paulo", "São Paulo, São Paulo", ("BR", "SP", "sao paulo", "fonte")),
    (None, None, None, "Barueri, São Paulo", ("BR", "SP", "barueri", "uf")),
    (None, None, None, "Remote - Brazil", ("BR", None, None, "local_raw")),
    (None, None, None, "São Paulo, Brazil", ("BR", "SP", "sao paulo", "local_raw")),
    (None, None, None, "Lisbon, Portugal", ("PT", None, "lisboa", "local_raw")),
    (None, None, None, "Porto, Portugal", ("PT", None, "porto", "local_raw")),
    (None, None, None, "Lisboa", ("PT", None, "lisboa", "cidade")),
    (None, None, None, "Bogotá, Colombia", ("CO", None, "bogota", "local_raw")),
    (None, None, None, "Ciudad de México, México", ("MX", None, "cidade do mexico", "local_raw")),
    (None, None, None, "Buenos Aires", ("AR", None, "buenos aires", "cidade")),
    (None, None, None, "Madrid, Spain", ("ES", None, "madrid", "local_raw")),   # ES não é Espírito Santo aqui
    ("PT", None, None, "Remote", ("PT", None, None, "fonte")),                 # código ISO no campo da fonte
    (None, None, None, "Remote - Brazil or Mexico", (None, None, None, "multiplos")),
    (None, None, None, "Remote, LATAM", (None, None, None, "nao_informada")),
    (None, None, None, None, (None, None, None, "nao_informada")),
    (None, None, None, "Porto Alegre, RS", ("BR", "RS", "porto alegre", "uf")),
])
def test_localizar(country, state, city, local, esperado):
    loc = localizar(country, state, city, local)
    assert (loc.pais_iso, loc.uf, loc.cidade_norm, loc.origem_pais) == esperado


def test_regiao_e_uf_no_brasil_e_estado_normalizado_fora():
    assert localizar("Brasil", "Minas Gerais", "Belo Horizonte", None).regiao == "MG"
    pt = localizar("Portugal", "Distrito de Lisboa", "Lisboa", None)
    assert pt.uf is None and pt.regiao == "distrito de lisboa" and pt.cidade_norm == "lisboa"


def _chave_antiga(empresa, titulo, uf):
    """Fórmula da chave alternativa antes da geografia (só UF): as vagas do Brasil não podem mudar."""
    return sha1(normalizar(empresa), " ".join(RUIDO_TITULO.sub(" ", normalizar(titulo)).split()), uf or "")


@pytest.mark.parametrize("country,state,local", [
    ("Brasil", "São Paulo", "São Paulo, São Paulo"),
    (None, None, "Remote - Brazil"),
    (None, None, None),
    (None, None, "Remote, LATAM"),
    (None, "RJ", "Rio de Janeiro"),
])
def test_chave_do_brasil_e_sem_pais_fica_identica_a_antiga(country, state, local):
    loc = localizar(country, state, None, local)
    nova = chave_alternativa("Acme", "Engenheira de Dados Jr", chave_local(loc.pais_iso, loc.uf, loc.regiao,
                                                                          loc.cidade_norm))
    assert nova == _chave_antiga("Acme", "Engenheira de Dados Jr", loc.uf)


def test_chave_separa_cidades_e_paises_fora_do_brasil():
    def chave(local):
        loc = localizar(None, None, None, local)
        return chave_alternativa("Acme", "Data Engineer", chave_local(loc.pais_iso, loc.uf, loc.regiao, loc.cidade_norm))
    assert chave("Lisbon, Portugal") == chave("Lisboa, Portugal")       # mesma cidade, grafias diferentes
    assert chave("Lisbon, Portugal") != chave("Porto, Portugal")
    assert chave("Lisbon, Portugal") != chave("Remote - Brazil")
    assert chave_remota(None) == chave_remota("BR") == "remoto" and chave_remota("PT") == "remoto:PT"
