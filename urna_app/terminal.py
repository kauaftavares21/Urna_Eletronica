"""Interface de terminal e dados auxiliares da simula??o."""

import random
import time
from datetime import date

from .core import (
    BRANCO,
    MIN_VOTOS,
    NULO,
    Candidato,
    Municipio,
    Urna,
    avaliar_resultado,
    preparar_segundo_turno,
)
from .database import DatabaseError

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
    """Exibe a decisão compartilhada; retorna os finalistas quando há 2º turno."""
    linha("─")
    decisao = avaliar_resultado(urna, r)
    if decisao["tipo"] == "sem":
        print(decisao["detalhe"])
        return None
    if decisao["tipo"] == "segundo":
        print(decisao["detalhe"])
        a, b = decisao["finalistas"]
        print(f"➡  2º TURNO entre {urna.candidatos[a].nome} e {urna.candidatos[b].nome}.")
        return decisao["finalistas"]
    n = decisao["eleito"]
    c = urna.candidatos[n]
    print(f"🏆 ELEITO(A): {c.nome} ({c.partido}). {decisao['detalhe']}")
    if decisao["nota"]:
        print(f"⚖  {decisao['nota']}")
    return None


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
    if not isinstance(qtd, int) or isinstance(qtd, bool) or qtd <= 0:
        raise ValueError("A quantidade de eleitores deve ser um inteiro positivo.")
    if qtd > urna.municipio.eleitorado:
        raise ValueError("A quantidade da seção não pode superar o eleitorado municipal.")
    titulos = []
    for i in range(qtd):
        for _ in range(100):
            tit = f"{random.randint(10**11, 10**12 - 1)}"
            if tit not in urna.eleitores_aptos:
                break
        else:
            tit = next((str(x) for x in range(10**11, 10**12)
                        if str(x) not in urna.eleitores_aptos), None)
            if tit is None:
                raise ValueError("Não foi possível gerar um título fictício único.")
        urna.registrar_eleitor(tit, f"{NOMES[i % len(NOMES)]} {i + 1:02d}")
        titulos.append(tit)
    return titulos


def escolher_municipio() -> Municipio:
    print("\nTipo de município:")
    print("  1) Exemplo didático de pequeno porte — 85.000 eleitores")
    print("  2) Exemplo didático de grande porte  — 450.000 eleitores")
    print("  3) Capital fictícia para demonstração — aplica-se o limite de eleitorado")
    print("  4) Personalizado")
    op = input("Opção: ").strip()
    while op not in {"1", "2", "3", "4"}:
        print("  Escolha uma opção de 1 a 4.")
        op = input("Opção: ").strip()
    if op == "1":
        return Municipio("Município Pequeno (exemplo)", 85_000)
    if op == "3":
        return Municipio("Capital Fictícia (exemplo)", 2_200_000, capital=True)
    if op == "4":
        nome = input("Nome do município: ").strip() or "Município"
        eleit = ler_inteiro("Eleitorado total: ", minimo=1)
        cap = input("É capital? (s/n): ").strip().lower() == "s"
        return Municipio(nome, eleit, cap)
    return Municipio("Município Grande (exemplo)", 450_000)


def ler_inteiro(prompt: str, minimo: int = 1, maximo: int | None = None) -> int:
    """Repete a pergunta até receber um inteiro dentro dos limites informados."""
    while True:
        valor = input(prompt).strip()
        try:
            numero = int(valor)
        except ValueError:
            print("  Informe um número inteiro válido.")
            continue
        if numero < minimo or (maximo is not None and numero > maximo):
            limite = f" e no máximo {maximo}" if maximo is not None else ""
            print(f"  Informe um valor entre {minimo}{limite}.")
            continue
        return numero


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
    titulo_tela("🇧🇷  URNA ELETRÔNICA — SIMULAÇÃO DIDÁTICA  🇧🇷")
    print("Modo:  1) Votação interativa   2) Simulação automática")
    modo = input("Opção: ").strip()
    while modo not in {"1", "2"}:
        print("  Digite 1 para votação interativa ou 2 para simulação automática.")
        modo = input("Opção: ").strip()

    municipio = escolher_municipio()
    regra = "maioria ABSOLUTA (pode haver 2º turno)" \
        if municipio.exige_maioria_absoluta else "maioria SIMPLES (turno único)"
    print(f"\n→ {municipio.nome}: regra aplicada = {regra}")

    urna = Urna(municipio)
    cadastrar_candidatos(urna)

    qtd = ler_inteiro(f"Quantidade de eleitores na seção (mín. {MIN_VOTOS}): ",
                      minimo=MIN_VOTOS, maximo=municipio.eleitorado)
    titulos = gerar_eleitores(urna, qtd)

    if modo == "2":
        # pesos que tendem a gerar disputa acirrada (e às vezes 2º turno)
        pesos = {"12": 30, "25": 28, "33": 20, "45": 12, BRANCO: 5, NULO: 5}
        pesos = {k: v for k, v in pesos.items() if k in urna.candidatos or k in (BRANCO, NULO)}
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
        try:
            urna2 = preparar_segundo_turno(urna, finalistas, imp or None)
        except (ValueError, RuntimeError) as e:
            print(f"Não foi possível preparar o segundo turno: {e}")
            finalistas = None
        if not finalistas:
            linha()
            print("Apuração concluída sem segundo turno.")
            return
        if imp:
            substituto = next((n for n in urna2.candidatos if n not in finalistas), None)
            if substituto:
                print(f"Candidato impedido substituído por {urna2.candidatos[substituto].nome}.")
        if modo == "2":
            pesos2 = {n: random.randint(40, 60) for n in urna2.candidatos}
            pesos2[BRANCO] = 4
            pesos2[NULO] = 3
            sessao_de_votacao_automatica(urna2, pesos2)
        else:
            sessao_de_votacao_interativa(urna2)
        r2 = boletim_de_urna(urna2)
        resultado(urna2, r2)

    linha()
    print("Apuração concluída. Obrigado por exercer a cidadania! 🗳️".center(LARG))
    linha()


def executar_terminal() -> None:
    """Executa o modo de terminal e converte falhas conhecidas em mensagens claras."""
    try:
        main()
    except DatabaseError as erro:
        print(f"Erro ao acessar o banco local: {erro}")
    except RuntimeError as erro:
        print(f"A execução foi interrompida: {erro}")


if __name__ == "__main__":
    executar_terminal()
