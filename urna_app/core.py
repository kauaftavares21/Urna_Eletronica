"""
Aluno: Kauã Fernandes
Matricula 202510928
Matéria: Tópicos Avançados em Análise e Desenvolvimento de Sistemas
Simulador didático de urna eletrônica municipal

Regras implementadas:
  * Município com até 200 mil eleitores  -> maioria simples (turno único)
  * Município com mais de 200 mil eleitores -> maioria absoluta
    dos votos válidos; se ninguém a atingir, há 2º turno entre os 2 primeiros.
  * Se, antes do 2º turno, houver morte, desistência ou impedimento legal de
    um candidato, é convocado o remanescente com a maior votação.
  * Votos válidos são os votos nominais; brancos e nulos ficam fora da conta.
  * Em caso de empate, vence o candidato mais idoso (critério didático).

Integridade:
  * Cada eleitor só pode votar uma vez por turno.
  * O voto é secreto: a urna guarda QUEM votou separado de EM QUEM se votou.
  * Cada voto gera um registro encadeado por hash SHA-256.
    na apuração a cadeia é verificada para detectar adulteração. É demonstração
    didática: não impede adulteração por quem controla os dados e recalcula hashes.
"""

from dataclasses import dataclass     # Biblioteca padrão para criar classes de dados
from datetime import date, datetime     # Biblioteca padrão para manipulação de datas
from .database import Database, DatabaseError, MIN_VOTOS

LIMITE_2_TURNO = 200_000

BRANCO = "BRANCO"
NULO = "NULO"


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------
@dataclass
class Candidato:
    numero: str
    nome: str
    partido: str
    nascimento: date
    apto: bool = True

    @property
    def idade(self) -> int:
        hoje = date.today()
        return hoje.year - self.nascimento.year - (
            (hoje.month, hoje.day) < (self.nascimento.month, self.nascimento.day)
        )


@dataclass
class Municipio:
    nome: str
    eleitorado: int
    capital: bool = False

    @property
    def exige_maioria_absoluta(self) -> bool:
        return self.eleitorado > LIMITE_2_TURNO


# ---------------------------------------------------------------------------
# Urna
# ---------------------------------------------------------------------------
class Urna:
    def __init__(self, municipio: Municipio, turno: int = 1, banco: Database | None = None,
                 eleicao_id: int | None = None, eleicao_pai_id: int | None = None):
        self.banco = banco or Database()
        self.municipio_id = self.banco.salvar_municipio(municipio)
        if eleicao_id is None:
            self.eleicao_id = self.banco.salvar_eleicao(self.municipio_id, turno, eleicao_pai_id)
            self.turno = turno
        else:
            registro = self.banco.obter_eleicao(eleicao_id)
            if not registro or registro["municipio_id"] != self.municipio_id:
                raise ValueError("Eleição persistida não encontrada para este município.")
            self.eleicao_id = eleicao_id
            self.turno = registro["turno"]
        self.municipio = municipio
        self.candidatos: dict[str, Candidato] = {}
        self.eleitores_aptos: dict[str, str] = {}   
        self.ja_votaram: set[str] = set()           
        self.cadeia: list[dict] = []                
        self.encerrada = False
        if eleicao_id is None:
            self.banco.registrar_evento_auditoria("configuracao_iniciada", "", self.eleicao_id)
        else:
            self._recuperar_estado()

    @classmethod
    def carregar(cls, banco: Database, eleicao_id: int) -> "Urna":
        registro = banco.obter_eleicao(eleicao_id)
        if not registro:
            raise ValueError("Eleição não encontrada.")
        municipio = Municipio(registro["municipio_nome"], registro["municipio_eleitorado"],
                              bool(registro["municipio_capital"]))
        return cls(municipio, banco=banco, eleicao_id=eleicao_id)

    def _recuperar_estado(self) -> None:
        registro = self.banco.obter_eleicao(self.eleicao_id)
        self.encerrada = registro["status"] == "encerrada"
        for row in self.banco.listar_candidatos(self.eleicao_id):
            c = Candidato(row["numero"], row["nome"], row["partido"], date.fromisoformat(row["nascimento"]),
                          bool(row["apto"]))
            self.candidatos[c.numero] = c
        for row in self.banco.listar_eleitores(self.eleicao_id):
            self.eleitores_aptos[row["titulo"]] = row["nome"]
            if row["ja_votou"]:
                self.ja_votaram.add(row["titulo"])
        self.cadeia = self._cadeia_em_memoria()

    def _cadeia_em_memoria(self) -> list[dict]:
        return [{"voto": r["voto"], "nonce": r["registrado_em"],
                 "anterior": r["hash_anterior"], "hash": r["hash_atual"]}
                for r in self.banco.listar_votos_para_apuracao(self.eleicao_id)]

    # ---------- cadastros ----------
    def cadastrar_candidato(self, c: Candidato) -> None:
        if not isinstance(c.numero, str) or not (c.numero.isascii() and c.numero.isdigit() and len(c.numero) == 2):
            raise ValueError("O número do candidato a prefeito deve ter 2 dígitos.")
        if c.numero in self.candidatos:
            raise ValueError(f"Número {c.numero} já pertence a "
                             f"{self.candidatos[c.numero].nome}.")
        if not isinstance(c.nome, str) or not c.nome.strip():
            raise ValueError("Informe o nome do candidato.")
        if not isinstance(c.partido, str) or not c.partido.strip():
            raise ValueError("Informe o partido do candidato.")
        if not isinstance(c.nascimento, date) or isinstance(c.nascimento, datetime) or c.nascimento >= date.today():
            raise ValueError("Informe uma data de nascimento válida e passada.")
        self.banco.salvar_candidato(self.eleicao_id, c)
        self.candidatos[c.numero] = c

    def registrar_eleitor(self, titulo: str, nome: str) -> None:
        if not isinstance(titulo, str) or not isinstance(nome, str) or not nome.strip():
            raise ValueError("Informe um título e um nome de eleitor válidos.")
        titulo = titulo.strip()
        if not titulo.isascii() or not titulo.isdigit():
            raise ValueError("Título de eleitor deve conter apenas números.")
        if titulo in self.eleitores_aptos:
            raise ValueError("Título já registrado nesta seção.")
        self.banco.salvar_eleitor(self.eleicao_id, titulo, nome)
        self.eleitores_aptos[titulo] = nome

    # ---------- votação ----------
    def liberar_eleitor(self, titulo: str) -> str:
        """Valida o eleitor (papel do mesário). Retorna o nome."""
        estado = self.banco.obter_eleicao(self.eleicao_id)
        if self.encerrada or not estado or estado["status"] == "encerrada":
            self.encerrada = True
            raise PermissionError("Votação encerrada.")
        if titulo not in self.eleitores_aptos:
            raise PermissionError("Eleitor não pertence a esta seção.")
        if titulo in self.ja_votaram or self.banco.eleitor_votou(self.eleicao_id, titulo):
            raise PermissionError("ELEITOR JÁ VOTOU! Tentativa de voto duplo bloqueada.")
        return self.eleitores_aptos[titulo]

    def classificar_voto(self, digitado: str) -> str:
        if digitado == BRANCO:
            return BRANCO
        c = self.candidatos.get(digitado)
        return digitado if c and c.apto else NULO

    def registrar_voto(self, titulo: str, digitado: str) -> None:
        self.liberar_eleitor(titulo)  # revalida (defesa em profundidade)
        voto = self.classificar_voto(digitado)
        registro = self.banco.registrar_voto(self.eleicao_id, self.turno, titulo, voto)
        self.ja_votaram.add(titulo)
        self.cadeia.append({"voto": voto, "nonce": registro["registrado_em"],
                            "anterior": registro["hash_anterior"], "hash": registro["hash_atual"]})

    def encerrar(self) -> None:
        if self.encerrada:
            return
        quantidade = len(self.banco.listar_votos_para_apuracao(self.eleicao_id))
        if quantidade < MIN_VOTOS:
            raise PermissionError(f"São necessários pelo menos {MIN_VOTOS} votos "
                                  f"para encerrar (há {quantidade}).")
        if not self.verificar_integridade():
            raise RuntimeError("A cadeia de votos está inconsistente; votação não pode ser encerrada.")
        self.banco.encerrar_eleicao(self.eleicao_id)
        self.encerrada = True

    # ---------- integridade ----------
    def verificar_integridade(self) -> bool:
        ok = self._integridade_valida()
        if not ok:
            try:
                self.banco.registrar_evento_auditoria(
                    "integridade_falhou", "Verificação da cadeia de votos", self.eleicao_id)
            except DatabaseError:
                pass
        return ok

    def _integridade_valida(self) -> bool:
        if not isinstance(self.cadeia, list) or not isinstance(self.ja_votaram, set) \
                or not isinstance(self.eleitores_aptos, dict):
            return False
        if not self.banco.verificar_integridade(self.eleicao_id):
            return False
        try:
            if self.cadeia != self._cadeia_em_memoria():
                return False
            banco_candidatos = self.banco.listar_candidatos(self.eleicao_id)
            candidatos_cache = [(n, c.nome, c.partido, c.nascimento.isoformat(), int(c.apto))
                                for n, c in sorted(self.candidatos.items())]
            candidatos_db = [(r["numero"], r["nome"], r["partido"], r["nascimento"], r["apto"])
                             for r in banco_candidatos]
            if candidatos_cache != candidatos_db:
                return False
            banco_eleitores = self.banco.listar_eleitores(self.eleicao_id)
            votaram = {r["titulo"] for r in banco_eleitores if r["ja_votou"]}
            if votaram != self.ja_votaram:
                return False
            if {r["titulo"]: r["nome"] for r in banco_eleitores} != self.eleitores_aptos:
                return False
        except (DatabaseError, KeyError, TypeError, ValueError):
            return False
        return (len(self.cadeia) == len(self.ja_votaram)
                and self.ja_votaram <= self.eleitores_aptos.keys())

    # ---------- apuração ----------
    def apurar(self) -> dict:
        if not self.verificar_integridade():
            raise RuntimeError("Cadeia de votos inválida; apuração cancelada.")
        contagem = {n: 0 for n in self.candidatos}
        brancos = nulos = 0
        for reg in self.cadeia:
            if reg["voto"] == BRANCO:
                brancos += 1
            elif reg["voto"] == NULO:
                nulos += 1
            elif reg["voto"] in contagem:
                contagem[reg["voto"]] += 1
        validos = sum(contagem.values())
        # ordena por votos e, no empate, pelo mais idoso
        ranking = sorted(
            ((n, votos) for n, votos in contagem.items() if self.candidatos[n].apto),
            key=lambda kv: (-kv[1], -self.candidatos[kv[0]].idade, kv[0]),
        )
        return {
            "ranking": ranking, "validos": validos, "brancos": brancos,
            "nulos": nulos, "total": len(self.cadeia),
            "comparecimento": len(self.ja_votaram),
            "aptos": len(self.eleitores_aptos),
        }


def avaliar_resultado(urna: Urna, r: dict) -> dict:
    """Aplica a regra eleitoral uma vez, compartilhada entre terminal e GUI."""
    if not r["ranking"]:
        return dict(tipo="sem", detalhe="Não há candidatos aptos para apuração.", nota="")
    validos = r["validos"]
    if validos == 0:
        return dict(tipo="sem", detalhe="Nenhum voto válido foi registrado.", nota="")
    n1, v1 = r["ranking"][0]
    pct = v1 / validos
    nota = ""
    if len(r["ranking"]) > 1 and r["ranking"][1][1] == v1:
        nota = (f"Empate em {v1} voto(s): vence o(a) candidato(a) mais idoso(a) "
                f"({urna.candidatos[n1].idade} anos).")

    if urna.turno == 2:
        return dict(tipo="eleito", eleito=n1, nota=nota,
                    detalhe=f"Eleito(a) no 2º turno com {pct:.1%} dos votos válidos.")
    if not urna.municipio.exige_maioria_absoluta:
        return dict(tipo="eleito", eleito=n1, nota=nota,
                    detalhe=f"Maioria simples, turno único: {v1} voto(s), {pct:.1%} dos válidos.")
    if v1 > validos / 2:
        return dict(tipo="eleito", eleito=n1, nota=nota,
                    detalhe=f"Maioria absoluta já no 1º turno: {pct:.1%} dos válidos.")

    if len(r["ranking"]) < 2:
        return dict(tipo="sem", detalhe="Não há dois candidatos aptos para o segundo turno.", nota=nota)
    n2 = r["ranking"][1][0]
    if len(r["ranking"]) > 2 and r["ranking"][1][1] == r["ranking"][2][1]:
        nota = "Empate no 2º lugar: classifica-se o(a) candidato(a) mais idoso(a)."
    return dict(tipo="segundo", finalistas=[n1, n2], nota=nota,
                detalhe=f"Ninguém passou de 50% dos votos válidos (o 1º colocado teve {pct:.1%}).")


def preparar_segundo_turno(urna1: Urna, finalistas: list[str],
                           impedido: str | None) -> Urna:
    """Cria a urna do 2º turno, aplicando a regra de convocação do remanescente."""
    if not urna1.encerrada:
        raise ValueError("Encerre o primeiro turno antes de preparar o segundo.")
    if not urna1.verificar_integridade():
        raise RuntimeError("Cadeia de votos do primeiro turno inválida.")
    finalistas = list(dict.fromkeys(finalistas))
    if len(finalistas) != 2 or any(n not in urna1.candidatos for n in finalistas):
        raise ValueError("O segundo turno exige dois finalistas cadastrados.")
    if impedido is not None:
        if impedido not in urna1.candidatos:
            raise ValueError("O candidato informado como impedido não existe.")
        if impedido not in finalistas:
            raise ValueError("O candidato impedido deve ser um dos dois finalistas.")
        urna1.banco.registrar_impedimento(urna1.eleicao_id, impedido)
        urna1.candidatos[impedido].apto = False
    impedidos = [n for n in finalistas if not urna1.candidatos[n].apto]
    if impedidos:
        restantes = [n for n, _ in urna1.apurar()["ranking"]
                     if n not in finalistas and urna1.candidatos[n].apto]
        for n in impedidos:
            if not restantes:
                raise ValueError("Não há candidato apto para substituir o finalista impedido.")
            convocado = restantes.pop(0)
            finalistas[finalistas.index(n)] = convocado
    if len(set(finalistas)) != 2 or any(not urna1.candidatos[n].apto for n in finalistas):
        raise ValueError("Não foi possível formar dois finalistas aptos.")

    candidatos = [urna1.candidatos[n] for n in finalistas]
    segundo_id = urna1.banco.criar_segundo_turno(urna1.eleicao_id, candidatos)
    return Urna.carregar(urna1.banco, segundo_id)
