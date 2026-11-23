"""
Simulador de Urna Eletrônica - Eleições Municipais 2026

Regras implementadas:
  * Município com até 200 mil eleitores  -> maioria simples (turno único)
  * Capital ou município com mais de 200 mil eleitores -> maioria absoluta
    dos votos válidos; se ninguém a atingir, há 2º turno entre os 2 primeiros.
  * Se, antes do 2º turno, houver morte, desistência ou impedimento legal de
    um candidato, é convocado o remanescente com a maior votação.
  * Votos válidos = votos nominais (brancos e nulos não entram na conta).
  * Empate: vence o candidato mais idoso (critério de desempate).

Integridade:
  * Cada eleitor só pode votar uma vez por turno.
  * O voto é secreto: a urna guarda QUEM votou separado de EM QUEM se votou.
  * Cada voto gera um registro encadeado por hash SHA-256 (estilo "blockchain");
    na apuração a cadeia é verificada para detectar adulteração.
"""

import hashlib
import random
import time
from dataclasses import dataclass
from datetime import date

MIN_VOTOS = 10            
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
    apto: bool = True  # False em caso de morte, desistência ou impedimento

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
        return self.capital or self.eleitorado > LIMITE_2_TURNO


# ---------------------------------------------------------------------------
# Urna
# ---------------------------------------------------------------------------
class Urna:
    def __init__(self, municipio: Municipio, turno: int = 1):
        self.municipio = municipio
        self.turno = turno
        self.candidatos: dict[str, Candidato] = {}
        self.eleitores_aptos: dict[str, str] = {}   
        self.ja_votaram: set[str] = set()           
        self.cadeia: list[dict] = []                
        self.encerrada = False

    # ---------- cadastros ----------
    def cadastrar_candidato(self, c: Candidato) -> None:
        if not (c.numero.isdigit() and len(c.numero) == 2):
            raise ValueError("O número do candidato a prefeito deve ter 2 dígitos.")
        if c.numero in self.candidatos:
            raise ValueError(f"Número {c.numero} já pertence a "
                             f"{self.candidatos[c.numero].nome}.")
        self.candidatos[c.numero] = c

    def registrar_eleitor(self, titulo: str, nome: str) -> None:
        titulo = titulo.strip()
        if not titulo.isdigit():
            raise ValueError("Título de eleitor deve conter apenas números.")
        if titulo in self.eleitores_aptos:
            raise ValueError("Título já registrado nesta seção.")
        self.eleitores_aptos[titulo] = nome

    # ---------- votação ----------
    def liberar_eleitor(self, titulo: str) -> str:
        """Valida o eleitor (papel do mesário). Retorna o nome."""
        if self.encerrada:
            raise PermissionError("Votação encerrada.")
        if titulo not in self.eleitores_aptos:
            raise PermissionError("Eleitor não pertence a esta seção.")
        if titulo in self.ja_votaram:
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
        self.ja_votaram.add(titulo)

        anterior = self.cadeia[-1]["hash"] if self.cadeia else "0" * 64
        nonce = random.getrandbits(64)
        conteudo = f"{anterior}|{voto}|{nonce}"
        self.cadeia.append({
            "voto": voto,
            "nonce": nonce,
            "anterior": anterior,
            "hash": hashlib.sha256(conteudo.encode()).hexdigest(),
        })

    def encerrar(self) -> None:
        if len(self.cadeia) < MIN_VOTOS:
            raise PermissionError(f"São necessários pelo menos {MIN_VOTOS} votos "
                                  f"para encerrar (há {len(self.cadeia)}).")
        self.encerrada = True

    # ---------- integridade ----------
    def verificar_integridade(self) -> bool:
        anterior = "0" * 64
        for reg in self.cadeia:
            conteudo = f"{anterior}|{reg['voto']}|{reg['nonce']}"
            if reg["anterior"] != anterior or \
               hashlib.sha256(conteudo.encode()).hexdigest() != reg["hash"]:
                return False
            anterior = reg["hash"]
        return len(self.cadeia) == len(self.ja_votaram)

    # ---------- apuração ----------
    def apurar(self) -> dict:
        contagem = {n: 0 for n in self.candidatos}
        brancos = nulos = 0
        for reg in self.cadeia:
            if reg["voto"] == BRANCO:
                brancos += 1
            elif reg["voto"] == NULO:
                nulos += 1
            else:
                contagem[reg["voto"]] += 1
        validos = sum(contagem.values())
        # ordena por votos e, no empate, pelo mais idoso
        ranking = sorted(
            contagem.items(),
            key=lambda kv: (kv[1], self.candidatos[kv[0]].idade),
            reverse=True,
        )
        return {
            "ranking": ranking, "validos": validos, "brancos": brancos,
            "nulos": nulos, "total": len(self.cadeia),
            "comparecimento": len(self.ja_votaram),
            "aptos": len(self.eleitores_aptos),
        }

LARG = 64


def linha(c="═"):
    print(c * LARG)


def titulo_tela(texto):
    linha()
    print(texto.center(LARG))
    linha()


def bip():
    print("\a", end="")


def tela_urna(urna: Urna, digitado: str) -> None:
    print("┌" + "─" * (LARG - 2) + "┐")
    print(f"│ {'SEU VOTO PARA':<{LARG - 4}} │")
    print(f"│ {'PREFEITO(A)':^{LARG - 4}} │")
    print(f"│ Número: [{digitado[:1] or ' '}] [{digitado[1:2] or ' '}]"
          f"{'':<{LARG - 21}}│")
    voto = urna.classificar_voto(digitado) if digitado else ""
    if voto == BRANCO:
        info = "VOTO EM BRANCO"
    elif voto == NULO:
        info = "NÚMERO ERRADO — VOTO NULO"
    elif voto:
        c = urna.candidatos[voto]
        info = f"{c.nome} ({c.partido})"
    else:
        info = ""
    print(f"│ {info:<{LARG - 4}} │")
    print(f"│ {'':<{LARG - 4}} │")
    print(f"│ {'[C] CONFIRMA   [L] CORRIGE   [B] BRANCO':<{LARG - 4}} │")
    print("└" + "─" * (LARG - 2) + "┘")


def sessao_de_votacao_interativa(urna: Urna) -> None:
    titulo_tela(f"{urna.turno}º TURNO — {urna.municipio.nome.upper()}")
    print("Candidatos:")
    for c in urna.candidatos.values():
        if c.apto:
            print(f"  {c.numero} - {c.nome} ({c.partido})")
    print(f"\nDigite o título do eleitor (ou FIM para encerrar; mínimo "
          f"{MIN_VOTOS} votos).")

    while True:
        print(f"\nVotos registrados: {len(urna.cadeia)}/{len(urna.eleitores_aptos)}")
        tit = input("Mesário — título do eleitor: ").strip().upper()
        if tit == "FIM":
            try:
                urna.encerrar()
                return
            except PermissionError as e:
                print(f"  ⚠  {e}")
                continue
        try:
            nome = urna.liberar_eleitor(tit)
        except PermissionError as e:
            print(f"  ⛔ {e}")
            continue
        print(f"  ✔ Eleitor(a) liberado(a): {nome}")

        digitado = ""
        while True:
            tela_urna(urna, digitado)
            tecla = input("Tecla: ").strip().upper()
            if tecla == "B":
                digitado = BRANCO
            elif tecla == "L":
                digitado = ""
            elif tecla == "C" and digitado and (digitado == BRANCO or len(digitado) == 2):
                urna.registrar_voto(tit, digitado)
                bip()
                print("\n" + "FIM".center(LARG, "*"))
                break
            elif tecla.isdigit() and digitado != BRANCO:
                digitado = (digitado + tecla)[:2]
            else:
                print("  Tecla inválida.")

        if len(urna.ja_votaram) == len(urna.eleitores_aptos):
            print("\nTodos os eleitores da seção votaram.")
            urna.encerrar()
            return


def sessao_de_votacao_automatica(urna: Urna, pesos: dict[str, float]) -> None:
    """Simula os eleitores votando, incluindo tentativas de fraude."""
    titulo_tela(f"{urna.turno}º TURNO — {urna.municipio.nome.upper()} (simulação)")
    opcoes = list(pesos.keys())
    titulos = list(urna.eleitores_aptos.keys())
    for i, tit in enumerate(titulos, 1):
        escolha = random.choices(opcoes, weights=pesos.values())[0]
        urna.registrar_voto(tit, escolha)
        exib = escolha if escolha not in urna.candidatos else \
            f"{escolha} ✓" if urna.candidatos[escolha].apto else f"{escolha} (inapto→nulo)"
        print(f"  Iteração {i:02d} | título ***{tit[-4:]} | voto registrado 🔒 "
              f"| hash {urna.cadeia[-1]['hash'][:12]}…")
        if i % 4 == 0:
            try:
                urna.registrar_voto(tit, opcoes[0])
            except PermissionError as e:
                print(f"     ⛔ Fraude bloqueada (título ***{tit[-4:]}): {e}")
        time.sleep(0.05)
    urna.encerrar()


def boletim_de_urna(urna: Urna) -> dict:
    r = urna.apurar()
    titulo_tela(f"BOLETIM DE URNA — {urna.turno}º TURNO")
    ok = urna.verificar_integridade()
    print(f"Município: {urna.municipio.nome}  |  Eleitorado oficial: "
          f"{urna.municipio.eleitorado:,}".replace(",", "."))
    print(f"Aptos na seção: {r['aptos']}  |  Comparecimento: {r['comparecimento']} "
          f"({r['comparecimento'] / r['aptos']:.0%})")
    print(f"Integridade da cadeia de votos: {'✅ ÍNTEGRA' if ok else '❌ VIOLADA'}")
    print(f"Hash final: {urna.cadeia[-1]['hash'] if urna.cadeia else '-'}")
    linha("─")
    for pos, (num, votos) in enumerate(r["ranking"], 1):
        c = urna.candidatos[num]
        pct = votos / r["validos"] if r["validos"] else 0
        barra = "█" * round(pct * 30)
        status = "" if c.apto else " [INAPTO]"
        print(f"{pos}º {num} {c.nome[:18]:<18} {votos:>3} {pct:>6.1%} {barra}{status}")
    linha("─")
    print(f"Votos válidos: {r['validos']}  |  Brancos: {r['brancos']}  "
          f"|  Nulos: {r['nulos']}  |  Total: {r['total']}")
    if not ok:
        raise RuntimeError("Urna adulterada! Apuração anulada.")
    return r


def resultado(urna: Urna, r: dict) -> list[str] | None:
    """Retorna None se houver eleito; senão, os 2 números que vão ao 2º turno."""
    linha("─")
    (n1, v1) = r["ranking"][0]
    validos = r["validos"]
    if validos == 0:
        print("Nenhum voto válido. Eleição sem vencedor.")
        return None

    if len(r["ranking"]) > 1 and r["ranking"][1][1] == v1:
        print(f"⚖  Empate em {v1} votos — desempate pelo candidato mais idoso "
              f"({urna.candidatos[n1].nome}, {urna.candidatos[n1].idade} anos).")

    if not urna.municipio.exige_maioria_absoluta or urna.turno == 2:
        regra = "maioria simples" if urna.turno == 1 else "2º turno"
        print(f"🏆 ELEITO(A) por {regra}: {urna.candidatos[n1].nome} "
              f"({urna.candidatos[n1].partido}) com {v1} votos.")
        return None

    if v1 > validos / 2:
        print(f"🏆 ELEITO(A) em 1º turno por maioria absoluta: "
              f"{urna.candidatos[n1].nome} com {v1 / validos:.1%} dos válidos.")
        return None

    n2 = r["ranking"][1][0]
    print(f"Ninguém atingiu mais de 50% dos válidos ({v1 / validos:.1%}).")
    print(f"➡  2º TURNO entre {urna.candidatos[n1].nome} e {urna.candidatos[n2].nome}.")
    return [n1, n2]


def preparar_segundo_turno(urna1: Urna, finalistas: list[str],
                           impedido: str | None) -> Urna:
    """Cria a urna do 2º turno, aplicando a regra de convocação do remanescente."""
    if impedido and impedido in finalistas:
        c = urna1.candidatos[impedido]
        c.apto = False
        print(f"\n⚠  {c.nome} ficou impedido(a) antes do 2º turno "
              f"(morte, desistência ou impedimento legal).")
        restantes = [n for n, _ in urna1.apurar()["ranking"]
                     if urna1.candidatos[n].apto and n not in finalistas]
        if restantes:
            convocado = restantes[0]
            finalistas = [n for n in finalistas if n != impedido] + [convocado]
            print(f"   Convocado(a) o(a) remanescente de maior votação: "
                  f"{urna1.candidatos[convocado].nome}.")

    urna2 = Urna(urna1.municipio, turno=2)
    for n in finalistas:
        c = urna1.candidatos[n]
        urna2.cadastrar_candidato(Candidato(c.numero, c.nome, c.partido, c.nascimento))
    for tit, nome in urna1.eleitores_aptos.items():
        urna2.registrar_eleitor(tit, nome)   # todos podem votar de novo no 2º turno
    return urna2


# ---------------------------------------------------------------------------
# Dados de exemplo e programa principal
# ---------------------------------------------------------------------------
CANDIDATOS_EXEMPLO = [
    Candidato("12", "Ana Beatriz Moura", "PCD", date(1971, 3, 14)),
    Candidato("25", "Carlos Eduardo Lima", "PLV", date(1965, 8, 2)),
    Candidato("33", "Fernanda Rocha", "PVA", date(1980, 11, 27)),
    Candidato("45", "João Pedro Alves", "PNR", date(1958, 5, 9)),
]

NOMES = ["Maria", "José", "Antônio", "Francisca", "Paulo", "Adriana", "Lucas",
         "Juliana", "Marcos", "Patrícia", "Rafael", "Camila", "Bruno", "Larissa",
         "Diego", "Aline", "Thiago", "Bianca", "Gustavo", "Renata", "Felipe", 
         "Carla", "Vinícius", "Amanda", "Rodrigo", "Juliana", "Leandro",]


def gerar_eleitores(urna: Urna, qtd: int) -> list[str]:
    titulos = []
    for i in range(qtd):
        tit = f"{random.randint(10**11, 10**12 - 1)}"
        urna.registrar_eleitor(tit, f"{NOMES[i % len(NOMES)]} {i + 1:02d}")
        titulos.append(tit)
    return titulos


def escolher_municipio() -> Municipio:
    print("\nTipo de município:")
    print("  1) Pequeno porte  — 85.000 eleitores (maioria simples)")
    print("  2) Grande porte   — 450.000 eleitores (maioria absoluta / 2º turno)")
    print("  3) Capital        — Brasília/DF (maioria absoluta / 2º turno)")
    print("  4) Personalizado")
    op = input("Opção: ").strip()
    if op == "1":
        return Municipio("Pirenópolis", 85_000)
    if op == "3":
        return Municipio("Capital Federal", 2_200_000, capital=True)
    if op == "4":
        nome = input("Nome do município: ").strip() or "Município"
        eleit = int(input("Eleitorado total: ").strip() or "100000")
        cap = input("É capital? (s/n): ").strip().lower() == "s"
        return Municipio(nome, eleit, cap)
    return Municipio("Águas Claras do Norte", 450_000)


def cadastrar_candidatos(urna: Urna) -> None:
    if input("Usar candidatos de exemplo? (s/n): ").strip().lower() != "n":
        for c in CANDIDATOS_EXEMPLO:
            urna.cadastrar_candidato(Candidato(c.numero, c.nome, c.partido, c.nascimento))
        return
    while True:
        try:
            num = input("Número (2 dígitos, vazio p/ terminar): ").strip()
            if not num:
                if len(urna.candidatos) >= 2:
                    return
                print("  Cadastre ao menos 2 candidatos.")
                continue
            nome = input("Nome: ").strip()
            partido = input("Partido: ").strip().upper()
            nasc = date.fromisoformat(input("Nascimento (AAAA-MM-DD): ").strip())
            urna.cadastrar_candidato(Candidato(num, nome, partido, nasc))
            print("  ✔ Candidato cadastrado.")
        except ValueError as e:
            print(f"  ⚠  {e}")


def main() -> None:
    titulo_tela("🇧🇷  URNA ELETRÔNICA — ELEIÇÕES MUNICIPAIS 2024  🇧🇷")
    print("Modo:  1) Votação interativa   2) Simulação automática")
    modo = input("Opção: ").strip()

    municipio = escolher_municipio()
    regra = "maioria ABSOLUTA (pode haver 2º turno)" \
        if municipio.exige_maioria_absoluta else "maioria SIMPLES (turno único)"
    print(f"\n→ {municipio.nome}: regra aplicada = {regra}")

    urna = Urna(municipio)
    cadastrar_candidatos(urna)

    qtd = max(MIN_VOTOS, int(input(f"Quantidade de eleitores na seção "
                                   f"(mín. {MIN_VOTOS}): ").strip() or MIN_VOTOS))
    titulos = gerar_eleitores(urna, qtd)

    if modo == "2":
        # pesos que tendem a gerar disputa acirrada (e às vezes 2º turno)
        pesos = {"12": 30, "25": 28, "33": 20, "45": 12, BRANCO: 5, "99": 5}
        pesos = {k: v for k, v in pesos.items() if k in urna.candidatos or k in (BRANCO, "99")}
        sessao_de_votacao_automatica(urna, pesos)
    else:
        print("\nTítulos dos eleitores da seção (cola do mesário):")
        for t in titulos:
            print(f"  {t} — {urna.eleitores_aptos[t]}")
        sessao_de_votacao_interativa(urna)

    r = boletim_de_urna(urna)
    finalistas = resultado(urna, r)

    if finalistas:
        imp = input("\nSimular morte/desistência/impedimento de um finalista antes "
                    f"do 2º turno? Digite o número ({'/'.join(finalistas)}) ou Enter: ").strip()
        urna2 = preparar_segundo_turno(urna, finalistas, imp or None)
        if modo == "2":
            pesos2 = {n: random.randint(40, 60) for n in urna2.candidatos}
            pesos2[BRANCO] = 4
            pesos2["99"] = 3
            sessao_de_votacao_automatica(urna2, pesos2)
        else:
            sessao_de_votacao_interativa(urna2)
        r2 = boletim_de_urna(urna2)
        resultado(urna2, r2)

    linha()
    print("Apuração concluída. Obrigado por exercer a cidadania! 🗳️".center(LARG))
    linha()


if __name__ == "__main__":
    main()