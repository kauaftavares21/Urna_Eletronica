"""
Interface gráfica da simulação didática de urna eletrônica municipal
Usa a urna e as regras definidas em urna_eletronica.py (deixe os dois na mesma pasta).

Execute:  python visual_urna.py

Telas:
  1. Configuração  — município, candidatos e tamanho da seção
  2. Votação       — painel do mesário + urna com teclado clicável
  3. Apuração      — boletim de urna com gráfico, integridade e resultado
                     (com 2º turno quando a regra exigir)
"""

import random      # Biblioteca padrão para gerar números aleatórios
import tkinter as tk      # Biblioteca padrão para interface gráfica
from datetime import date, datetime      # Biblioteca padrão para manipulação de datas
from tkinter import filedialog, messagebox, ttk      # Biblioteca padrão para diálogos e widgets avançados
from .database import Database, DatabaseError

from .core import (BRANCO, MIN_VOTOS, NULO, Candidato, Municipio, Urna,
                   avaliar_resultado, preparar_segundo_turno)
from .terminal import CANDIDATOS_EXEMPLO, gerar_eleitores

# ---------------------------------------------------------------------------
# Aparência
# ---------------------------------------------------------------------------
C = dict(
    fundo="#eef1f5", azul="#0b3d91", azul2="#1d5bbf", texto="#1f2937",
    cinza="#6b7280", borda="#d5dae1", corpo="#3d3d3d", corpo2="#262626",
    tela="#f4f2e8", tecla="#161616", branco="#f7f7f7", laranja="#e8892b",
    verde="#2e9e48", vermelho="#c0392b", desativado="#b0b7c3",
)
CORES_CAND = ["#1d5bbf", "#e8892b", "#2e9e48", "#8e44ad",
              "#c0392b", "#16a085", "#d35400", "#2c3e50"]
FONTE = "Helvetica"


def f(tam, peso="normal"):
    return (FONTE, tam, peso)


_cores: dict = {}


def cor_de(numero: str) -> str:
    """Cada candidato mantém a mesma cor durante toda a eleição (1º e 2º turnos)."""
    if numero not in _cores:
        _cores[numero] = CORES_CAND[len(_cores) % len(CORES_CAND)]
    return _cores[numero]


def mascarar(titulo: str) -> str:
    return "***" + titulo[-4:] if len(titulo) > 4 else titulo


def clarear(hexcor: str, fator=0.18) -> str:
    r, g, b = (int(hexcor[i:i + 2], 16) for i in (1, 3, 5))
    r, g, b = (round(v + (255 - v) * fator) for v in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def avatar(cv: tk.Canvas, x, y, r, nome, cor):
    """'Foto' do candidato: círculo colorido com as iniciais."""
    partes = nome.split()
    ini = (partes[0][0] + (partes[-1][0] if len(partes) > 1 else "")).upper()
    cv.create_oval(x - r, y - r, x + r, y + r, fill=cor, outline="white", width=3)
    cv.create_text(x, y, text=ini, fill="white", font=f(max(9, int(r * 0.7)), "bold"))


def card(master, titulo=None):
    fr = tk.Frame(master, bg="white", highlightbackground=C["borda"],
                  highlightthickness=1)
    if titulo:
        tk.Label(fr, text=titulo, bg="white", fg=C["azul"],
                 font=f(12, "bold")).pack(anchor="w", padx=14, pady=(10, 4))
    return fr


class Botao(tk.Label):
    """Botão colorido que funciona igual em Windows, Linux e macOS."""

    def __init__(self, master, texto, comando, bg=None, fg="white", fonte=None, **kw):
        bg = bg or C["azul"]
        super().__init__(master, text=texto, bg=bg, fg=fg, font=fonte or f(11, "bold"),
                         padx=kw.pop("padx", 14), pady=kw.pop("pady", 8),
                         cursor="hand2", **kw)
        self.cor, self.comando, self.ativo = bg, comando, True
        self.bind("<Button-1>", self._clique)
        self.bind("<Enter>", lambda e: self.ativo and self.config(bg=clarear(self.cor)))
        self.bind("<Leave>", lambda e: self.config(bg=self.cor if self.ativo else C["desativado"]))

    def _clique(self, _):
        if self.ativo:
            self.comando()

    def set_ativo(self, ativo: bool):
        self.ativo = ativo
        self.config(bg=self.cor if ativo else C["desativado"],
                    cursor="hand2" if ativo else "arrow")


class Tecla(tk.Label):
    """Tecla física da urna (afunda ao clicar)."""

    def __init__(self, master, texto, comando, bg, fg="white", fonte=None, **kw):
        super().__init__(master, text=texto, bg=bg, fg=fg, font=fonte or f(18, "bold"),
                         relief="raised", bd=3, cursor="hand2", **kw)
        self.comando = comando
        self.bind("<Button-1>", lambda e: self.config(relief="sunken"))
        self.bind("<ButtonRelease-1>", self._solta)

    def _solta(self, _):
        self.config(relief="raised")
        self.comando()


# Regras de resultado
def decidir(urna: Urna, r: dict) -> dict:
    """Compatibilidade local: delega toda decisão eleitoral à lógica central."""
    return avaliar_resultado(urna, r)


def montar_segundo_turno(urna1: Urna, finalistas: list, impedido):
    """Cria a urna do 2º turno; aplica a convocação do remanescente se preciso."""
    aviso = None
    if impedido:
        aviso = (f"{urna1.candidatos[impedido].nome} ficou impedido(a) antes do 2º turno.")
    urna2 = preparar_segundo_turno(urna1, finalistas, impedido)
    if impedido:
        convocados = [n for n in urna2.candidatos if n != impedido]
        if len(convocados) == 2 and any(n not in finalistas for n in convocados):
            substituto = next(n for n in convocados if n not in finalistas)
            aviso += (f" Foi convocado(a) {urna1.candidatos[substituto].nome}, "
                      "remanescente com a maior votação.")
    return urna2, aviso

# Janela principal
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.banco = Database()
        self.title("Urna Eletrônica — Simulação didática")
        self.geometry("1260x780")
        self.minsize(1120, 720)
        self.configure(bg=C["fundo"])

        st = ttk.Style(self)
        st.theme_use("clam")
        st.configure("Treeview", rowheight=24, font=f(10), fieldbackground="white")
        st.configure("Treeview.Heading", font=f(10, "bold"))
        st.configure("Horizontal.TProgressbar", thickness=14,
                     background=C["verde"], troughcolor="#e5e7eb")

        cab = tk.Frame(self, bg=C["azul"])
        cab.pack(fill="x")
        tk.Label(cab, text="▣  URNA ELETRÔNICA", bg=C["azul"], fg="white",
                 font=f(17, "bold")).pack(side="left", padx=(20, 12), pady=12)
        tk.Label(cab, text="Simulação municipal · Prefeito(a)", bg=C["azul"],
                 fg="#c7d6f5", font=f(11)).pack(side="left")
        tk.Label(cab, text="Modelo educacional · regras simplificadas",
                 bg=C["azul"], fg="#c7d6f5", font=f(9)).pack(side="right", padx=20)

        self.area = tk.Frame(self, bg=C["fundo"])
        self.area.pack(fill="both", expand=True, padx=16, pady=12)
        self.mostrar(TelaConfig)

    def mostrar(self, tela, **kw):
        self.unbind("<Key>")
        for w in self.area.winfo_children():
            w.destroy()
        self.tela = tela(self.area, self, **kw)
        self.tela.pack(fill="both", expand=True)


# Tela 1 — Configuração
PRESETS = {
    "Pequeno porte (exemplo didático)": ("Município Pequeno (exemplo)", 85_000, False),
    "Grande porte (exemplo didático)": ("Município Grande (exemplo)", 450_000, False),
    "Capital fictícia (exemplo didático)": ("Capital Fictícia (exemplo)", 2_200_000, True),
    "Personalizado": ("Meu Município", 150_000, False),
}


class TelaConfig(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg=C["fundo"])
        self.app = app
        self.candidatos = self._exemplo()

        esq = tk.Frame(self, bg=C["fundo"], width=360)
        esq.pack(side="left", fill="y", padx=(0, 12))
        dir_ = tk.Frame(self, bg=C["fundo"])
        dir_.pack(side="left", fill="both", expand=True)

        # Município
        m = card(esq, "1. Município")
        m.pack(fill="x")
        self.preset = tk.StringVar(value=list(PRESETS)[1])
        for nome in PRESETS:
            tk.Radiobutton(m, text=nome, variable=self.preset, value=nome,
                           command=self.aplicar_preset, bg="white", anchor="w",
                           font=f(10), activebackground="white",
                           highlightthickness=0).pack(fill="x", padx=14)
        form = tk.Frame(m, bg="white")
        form.pack(fill="x", padx=14, pady=8)
        self.v_nome, self.v_eleit = tk.StringVar(), tk.StringVar()
        self.v_cap = tk.BooleanVar()
        for i, (rot, var) in enumerate([("Nome:", self.v_nome), ("Eleitorado:", self.v_eleit)]):
            tk.Label(form, text=rot, bg="white", font=f(10)).grid(row=i, column=0, sticky="w", pady=2)
            ttk.Entry(form, textvariable=var, width=26).grid(row=i, column=1, sticky="w", padx=6)
        tk.Checkbutton(form, text="É capital", variable=self.v_cap, bg="white",
                       font=f(10), activebackground="white",
                       highlightthickness=0).grid(row=2, column=1, sticky="w")
        self.lbl_regra = tk.Label(m, bg="#eaf1fb", fg=C["azul"], font=f(10, "bold"),
                                  wraplength=310, justify="left", anchor="w",
                                  padx=10, pady=8)
        self.lbl_regra.pack(fill="x", padx=14, pady=(0, 14))
        self.v_eleit.trace_add("write", lambda *a: self.atualizar_regra())
        self.v_cap.trace_add("write", lambda *a: self.atualizar_regra())

        # Seção
        s = card(esq, "3. Seção eleitoral")
        s.pack(fill="x", pady=12)
        linha = tk.Frame(s, bg="white")
        linha.pack(fill="x", padx=14, pady=(0, 14))
        tk.Label(linha, text=f"Eleitores aptos (mín. {MIN_VOTOS}):", bg="white",
                 font=f(10)).pack(side="left")
        self.v_qtd = tk.StringVar(value="15")
        ttk.Spinbox(linha, from_=MIN_VOTOS, to=500, textvariable=self.v_qtd,
                    width=6).pack(side="left", padx=8)
        tk.Label(s, text="Os títulos de eleitor são gerados automaticamente.",
                 bg="white", fg=C["cinza"], font=f(9)).pack(anchor="w", padx=14, pady=(0, 12))

        Botao(esq, "INICIAR VOTAÇÃO  ▶", self.iniciar, bg=C["verde"],
              fonte=f(13, "bold"), pady=12).pack(fill="x", pady=4)
        Botao(esq, "Consultar eleições salvas", lambda: self.app.mostrar(TelaHistorico),
              bg=C["cinza"], fonte=f(10)).pack(fill="x", pady=4)

        # Candidatos
        cc = card(dir_, "2. Candidatos a Prefeito(a)")
        cc.pack(fill="both", expand=True)
        cols = ("num", "nome", "partido", "nasc", "idade")
        self.tree = ttk.Treeview(cc, columns=cols, show="headings", height=8)
        for col, txt, w in zip(cols, ("Nº", "Nome", "Partido", "Nascimento", "Idade"),
                               (50, 260, 90, 110, 60)):
            self.tree.heading(col, text=txt)
            self.tree.column(col, width=w, anchor="w" if col == "nome" else "center")
        self.tree.pack(fill="both", expand=True, padx=14, pady=4)

        add = tk.Frame(cc, bg="white")
        add.pack(fill="x", padx=14, pady=8)
        self.e = {}
        for i, (rot, chave, larg) in enumerate([("Nº", "num", 5), ("Nome", "nome", 26),
                                                 ("Partido", "partido", 8),
                                                 ("Nascimento (DD/MM/AAAA)", "nasc", 14)]):
            tk.Label(add, text=rot, bg="white", fg=C["cinza"], font=f(9)).grid(row=0, column=i, sticky="w", padx=(0, 8))
            self.e[chave] = ttk.Entry(add, width=larg)
            self.e[chave].grid(row=1, column=i, sticky="w", padx=(0, 8))
        Botao(add, "+ Adicionar", self.adicionar, bg=C["azul2"]).grid(row=1, column=4)

        acoes = tk.Frame(cc, bg="white")
        acoes.pack(fill="x", padx=14, pady=(0, 14))
        Botao(acoes, "Remover selecionado", self.remover, bg=C["vermelho"]).pack(side="left")
        Botao(acoes, "Restaurar exemplo", self.restaurar, bg=C["cinza"]).pack(side="left", padx=8)
        tk.Label(acoes, text="Números com 2 dígitos. Mínimo de 2 candidatos.",
                 bg="white", fg=C["cinza"], font=f(9)).pack(side="right")

        self.aplicar_preset()
        self.atualizar_lista()

    @staticmethod
    def _exemplo():
        return [Candidato(c.numero, c.nome, c.partido, c.nascimento) for c in CANDIDATOS_EXEMPLO]

    def aplicar_preset(self):
        nome, eleit, cap = PRESETS[self.preset.get()]
        self.v_nome.set(nome)
        self.v_eleit.set(f"{eleit}")
        self.v_cap.set(cap)

    def _eleitorado(self):
        return int(self.v_eleit.get().replace(".", "").replace(" ", ""))

    def atualizar_regra(self):
        try:
            mun = Municipio("x", self._eleitorado(), self.v_cap.get())
        except ValueError:
            self.lbl_regra.config(text="Informe o eleitorado em números.")
            return
        if mun.exige_maioria_absoluta:
            txt = ("Regra: MAIORIA ABSOLUTA dos votos válidos.\n"
                   "Se ninguém passar de 50%, haverá 2º turno.")
        else:
            txt = "Regra: MAIORIA SIMPLES, turno único.\nQuem tiver mais votos se elege."
        self.lbl_regra.config(text=txt)

    def atualizar_lista(self):
        self.tree.delete(*self.tree.get_children())
        for c in sorted(self.candidatos, key=lambda c: c.numero):
            self.tree.insert("", "end", iid=c.numero, values=(
                c.numero, c.nome, c.partido, c.nascimento.strftime("%d/%m/%Y"), c.idade))

    def adicionar(self):
        num = self.e["num"].get().strip()
        nome = self.e["nome"].get().strip()
        partido = self.e["partido"].get().strip().upper()
        try:
            nasc = datetime.strptime(self.e["nasc"].get().strip(), "%d/%m/%Y").date()
        except ValueError:
            return messagebox.showwarning("Data inválida", "Use o formato DD/MM/AAAA.")
        if not (num.isdigit() and len(num) == 2):
            return messagebox.showwarning("Número inválido", "O número deve ter 2 dígitos.")
        if any(c.numero == num for c in self.candidatos):
            return messagebox.showwarning("Número repetido", f"O número {num} já está em uso.")
        if not nome or not partido:
            return messagebox.showwarning("Dados incompletos", "Preencha nome e partido.")
        if nasc >= date.today():
            return messagebox.showwarning("Data inválida", "A data de nascimento deve estar no passado.")
        self.candidatos.append(Candidato(num, nome, partido, nasc))
        for e in self.e.values():
            e.delete(0, "end")
        self.atualizar_lista()

    def remover(self):
        sel = set(self.tree.selection())
        self.candidatos = [c for c in self.candidatos if c.numero not in sel]
        self.atualizar_lista()

    def restaurar(self):
        self.candidatos = self._exemplo()
        self.atualizar_lista()

    def iniciar(self):
        if len(self.candidatos) < 2:
            return messagebox.showwarning("Candidatos", "Cadastre pelo menos 2 candidatos.")
        try:
            eleitorado = self._eleitorado()
            qtd = int(self.v_qtd.get())
        except ValueError:
            return messagebox.showwarning("Dados inválidos", "Eleitorado e quantidade devem ser números.")
        if eleitorado <= 0:
            return messagebox.showwarning("Eleitorado", "Informe um eleitorado municipal positivo.")
        if qtd < MIN_VOTOS:
            return messagebox.showwarning("Seção", f"A seção precisa de pelo menos {MIN_VOTOS} eleitores.")
        if qtd > eleitorado:
            return messagebox.showwarning("Seção", "A quantidade da seção não pode superar o eleitorado municipal.")
        try:
            urna = Urna(Municipio(self.v_nome.get().strip() or "Município", eleitorado,
                                  self.v_cap.get()), banco=self.app.banco)
        except (DatabaseError, ValueError):
            return messagebox.showerror("Banco de dados", "Não foi possível criar a eleição no banco local.")
        try:
            for c in self.candidatos:
                urna.cadastrar_candidato(Candidato(c.numero, c.nome, c.partido, c.nascimento))
            gerar_eleitores(urna, qtd)
        except (DatabaseError, ValueError):
            return messagebox.showerror("Cadastro", "Não foi possível salvar os candidatos ou eleitores.")
        _cores.clear()
        for c in sorted(self.candidatos, key=lambda c: c.numero):
            cor_de(c.numero)
        self.app.mostrar(TelaVotacao, urna=urna)


class TelaHistorico(tk.Frame):
    """Consulta eleições anteriores e retoma uma votação ainda aberta."""

    def __init__(self, master, app):
        super().__init__(master, bg=C["fundo"])
        self.app = app
        tk.Label(self, text="Eleições salvas neste computador", bg=C["fundo"],
                 fg=C["azul"], font=f(16, "bold")).pack(anchor="w", pady=(8, 12))
        self.tree = ttk.Treeview(self, columns=("id", "municipio", "turno", "status", "votos"),
                                 show="headings", height=16)
        for col, titulo, largura in (("id", "ID", 60), ("municipio", "Município", 350),
                                     ("turno", "Turno", 80), ("status", "Status", 130),
                                     ("votos", "Registros", 100)):
            self.tree.heading(col, text=titulo)
            self.tree.column(col, width=largura, anchor="center" if col != "municipio" else "w")
        self.tree.pack(fill="both", expand=True)
        try:
            for row in app.banco.listar_eleicoes():
                self.tree.insert("", "end", iid=str(row["id"]), values=(
                    row["id"], row["municipio"], f"{row['turno']}º", row["status"], row["votos"]))
        except DatabaseError:
            messagebox.showerror("Banco de dados", "Não foi possível consultar o histórico local.")
        acoes = tk.Frame(self, bg=C["fundo"])
        acoes.pack(fill="x", pady=12)
        Botao(acoes, "Voltar", lambda: app.mostrar(TelaConfig), bg=C["cinza"]).pack(side="left")
        Botao(acoes, "Abrir eleição selecionada", self.abrir, bg=C["azul"]).pack(side="right")

    def abrir(self):
        selecao = self.tree.selection()
        if not selecao:
            return messagebox.showinfo("Histórico", "Selecione uma eleição para abrir.")
        try:
            urna = Urna.carregar(self.app.banco, int(selecao[0]))
        except (DatabaseError, ValueError):
            return messagebox.showerror("Banco de dados", "Não foi possível recuperar essa eleição.")
        if urna.encerrada:
            self.app.mostrar(TelaResultado, urna=urna)
        elif urna.candidatos and urna.eleitores_aptos:
            self.app.mostrar(TelaVotacao, urna=urna)
        else:
            messagebox.showinfo("Eleição incompleta", "Essa eleição ainda não tem candidatos e eleitores suficientes.")


# Tela 2 — Votação
class TelaVotacao(tk.Frame):
    W, H = 400, 300  # tela da urna

    def __init__(self, master, app, urna: Urna, aviso=None):
        super().__init__(master, bg=C["fundo"])
        self.app, self.urna = app, urna
        self.titulo_atual = None
        self.digitado = ""
        self.estado = "aguardando"
        self.simulando = False

        dir_ = tk.Frame(self, bg=C["fundo"])
        dir_.pack(side="right", fill="y")
        esq = tk.Frame(self, bg=C["fundo"])
        esq.pack(side="left", fill="both", expand=True, padx=(0, 12))

        info = card(esq)
        info.pack(fill="x")
        mun = urna.municipio
        tk.Label(info, text=f"{urna.turno}º TURNO · {mun.nome}", bg="white",
                 fg=C["azul"], font=f(14, "bold")).pack(anchor="w", padx=14, pady=(10, 0))
        regra = ("Maioria absoluta dos válidos" if mun.exige_maioria_absoluta and urna.turno == 1
                 else "2º turno: vence quem tiver mais votos" if urna.turno == 2
                 else "Maioria simples, turno único")
        tk.Label(info, text=f"Eleitorado: {mun.eleitorado:,}".replace(",", ".")
                 + f"   ·   Regra: {regra}", bg="white", fg=C["cinza"],
                 font=f(10)).pack(anchor="w", padx=14, pady=(0, 10))
        if aviso:
            tk.Label(info, text="⚠ " + aviso, bg="#fff4d6", fg="#7a5200", font=f(10),
                     wraplength=440, justify="left", anchor="w", padx=10, pady=6).pack(fill="x", padx=14, pady=(0, 10))

        # Mesário
        mes = card(esq, "Mesário · liberação do eleitor")
        mes.pack(fill="both", expand=True, pady=10)
        cols = ("titulo", "nome", "situacao")
        self.tree = ttk.Treeview(mes, columns=cols, show="headings", height=4)
        for col, txt, w in zip(cols, ("Título", "Eleitor(a)", "Situação"), (120, 150, 90)):
            self.tree.heading(col, text=txt)
            self.tree.column(col, width=w, anchor="center" if col != "nome" else "w")
        self.tree.tag_configure("votou", foreground=C["verde"])
        for tit, nome in urna.eleitores_aptos.items():
            self.tree.insert("", "end", iid=tit, values=(tit, nome, "aguardando"))
        self.tree.pack(fill="both", expand=True, padx=14)
        self.tree.bind("<<TreeviewSelect>>", self._selecionou)
        self.tree.bind("<Double-1>", lambda e: self.liberar())

        lin = tk.Frame(mes, bg="white")
        lin.pack(fill="x", padx=14, pady=8)
        tk.Label(lin, text="Título:", bg="white", font=f(10)).pack(side="left")
        self.v_tit = tk.StringVar()
        self.ent_tit = tk.Entry(lin, textvariable=self.v_tit, width=16, font=f(11),
                                relief="solid", bd=1)
        self.ent_tit.pack(side="left", padx=6, ipady=3)
        Botao(lin, "Liberar urna", self.liberar, bg=C["azul2"]).pack(side="left")
        self.lbl_cabine = tk.Label(mes, text="Cabine livre", bg="white", fg=C["cinza"],
                                   font=f(10, "bold"))
        self.lbl_cabine.pack(anchor="w", padx=14, pady=(0, 10))
        # lista do mesário encolhe primeiro; campo do título sempre visível
        for w in (self.tree, lin, self.lbl_cabine):
            w.pack_forget()
        self.lbl_cabine.pack(side="bottom", anchor="w", padx=14, pady=(0, 10))
        lin.pack(side="bottom", fill="x", padx=14, pady=8)
        self.tree.pack(fill="both", expand=True, padx=14)

        # Progresso
        pr = card(esq)
        pr.pack(fill="x")
        self.lbl_prog = tk.Label(pr, bg="white", font=f(10, "bold"), fg=C["texto"])
        self.lbl_prog.pack(anchor="w", padx=14, pady=(10, 4))
        self.pb = ttk.Progressbar(pr, maximum=len(urna.eleitores_aptos))
        self.pb.pack(fill="x", padx=14)
        bts = tk.Frame(pr, bg="white")
        bts.pack(fill="x", padx=14, pady=10)
        self.b_sim = Botao(bts, "⟳ Simular eleitores restantes", self.simular, bg=C["azul2"])
        self.b_sim.pack(side="left")
        self.b_enc = Botao(bts, "Encerrar e apurar  ▶", self.encerrar, bg=C["vermelho"])
        self.b_enc.pack(side="right")

        # --- ocorrências ---
        lg = card(esq, "Registro de ocorrências")
        lg.pack(fill="x", pady=(10, 0))
        self.log = tk.Text(lg, height=4, font=("Courier", 9), bg="#fafafa",
                           relief="flat", state="disabled", wrap="word")
        self.log.pack(fill="x", padx=14, pady=(0, 12))
        for tag, cor in (("ok", C["verde"]), ("erro", C["vermelho"]), ("info", C["cinza"])):
            self.log.tag_configure(tag, foreground=cor)

        # os painéis de baixo têm prioridade; a lista do mesário ocupa o que sobrar
        for w in (mes, pr, lg):
            w.pack_forget()
        lg.pack(side="bottom", fill="x", pady=(10, 0))
        pr.pack(side="bottom", fill="x")
        mes.pack(fill="both", expand=True, pady=10)

        self._montar_urna(dir_)
        app.bind("<Key>", self._teclado)
        self.desenhar_tela()
        self.atualizar_progresso()
        self.registrar(f"Urna pronta: {len(urna.eleitores_aptos)} eleitores aptos, "
                       f"{len(urna.candidatos)} candidatos.", "info")

    # ---------- montagem da urna ----------
    def _montar_urna(self, master):
        corpo = tk.Frame(master, bg=C["corpo"], padx=18, pady=14,
                         highlightbackground="#1b1b1b", highlightthickness=2)
        corpo.pack()
        topo = tk.Frame(corpo, bg=C["corpo"])
        topo.pack(fill="x", pady=(0, 10))
        tk.Label(topo, text="JUSTIÇA ELEITORAL", bg=C["corpo"], fg="white",
                 font=f(12, "bold")).pack(side="left")
        self.luz = tk.Canvas(topo, width=110, height=18, bg=C["corpo"], highlightthickness=0)
        self.luz.pack(side="right")

        corpo_lin = tk.Frame(corpo, bg=C["corpo"])
        corpo_lin.pack()
        moldura = tk.Frame(corpo_lin, bg="#111", padx=6, pady=6)
        moldura.pack(side="left", padx=(0, 16))
        self.cv = tk.Canvas(moldura, width=self.W, height=self.H, bg=C["tela"],
                            highlightthickness=0)
        self.cv.pack()

        kb = tk.Frame(corpo_lin, bg=C["corpo2"], padx=12, pady=12)
        kb.pack(side="left", fill="y")
        for i, d in enumerate("123456789"):
            Tecla(kb, d, lambda d=d: self.digito(d), C["tecla"], width=2) \
                .grid(row=i // 3, column=i % 3, padx=4, pady=4, sticky="nsew")
        Tecla(kb, "0", lambda: self.digito("0"), C["tecla"], width=2) \
            .grid(row=3, column=1, padx=4, pady=4, sticky="nsew")
        fe = f(8, "bold")
        Tecla(kb, "BRANCO", self.branco, C["branco"], fg="#111", fonte=fe, pady=10) \
            .grid(row=4, column=0, padx=3, pady=(14, 4), sticky="nsew")
        Tecla(kb, "CORRIGE", self.corrige, C["laranja"], fg="#111", fonte=fe, pady=10) \
            .grid(row=4, column=1, padx=3, pady=(14, 4), sticky="nsew")
        Tecla(kb, "CONFIRMA", self.confirma, C["verde"], fg="#111", fonte=fe, pady=16) \
            .grid(row=4, column=2, padx=3, pady=(14, 4), sticky="nsew")

        dica = card(master)
        dica.pack(fill="x", pady=(12, 0))
        tk.Label(dica, text="Atalhos do teclado:  0–9 dígitos  ·  Enter = CONFIRMA  ·  "
                            "Backspace = CORRIGE  ·  B = BRANCO\nMesário: selecione o eleitor "
                            "na lista (duplo clique libera).",
                 bg="white", fg=C["cinza"], font=f(9), justify="left",
                 wraplength=620).pack(anchor="w", padx=12, pady=8)

    # ---------- desenho da tela ----------
    def desenhar_tela(self):
        cv, W, H = self.cv, self.W, self.H
        cv.delete("all")
        # luz "eleitor na cabine"
        self.luz.delete("all")
        na_cabine = self.estado == "votando"
        self.luz.create_oval(2, 3, 14, 15, fill="#33dd55" if na_cabine else "#663333", outline="")
        self.luz.create_text(20, 9, text="LIBERADA" if na_cabine else "BLOQUEADA",
                             anchor="w", fill="#ddd", font=f(8, "bold"))

        if self.estado == "aguardando":
            cv.create_text(W / 2, H / 2 - 22, text="AGUARDANDO", font=f(24, "bold"), fill=C["texto"])
            cv.create_text(W / 2, H / 2 + 14, text="liberação do mesário", font=f(13), fill=C["cinza"])
            cv.create_text(W / 2, H - 22, text=f"{self.urna.turno}º turno · {self.urna.municipio.nome}",
                           font=f(9), fill=C["cinza"])
            return
        if self.estado == "fim":
            cv.create_text(W / 2, H / 2, text="FIM", font=(FONTE, 80, "bold"), fill=C["texto"])
            return

        cv.create_text(16, 18, text="SEU VOTO PARA", anchor="w", font=f(10, "bold"))
        cv.create_text(W / 2, 50, text="PREFEITO(A)", font=f(20, "bold"))

        if self.digitado == BRANCO:
            cv.create_text(W / 2, 145, text="VOTO EM BRANCO", font=f(26, "bold"))
        else:
            cv.create_text(16, 106, text="Número:", anchor="w", font=f(13))
            for i in range(2):
                x = 100 + i * 46
                atual = i == len(self.digitado)
                cv.create_rectangle(x, 84, x + 38, 128, fill="white",
                                    outline=C["azul2"] if atual else C["texto"],
                                    width=3 if atual else 2)
                if i < len(self.digitado):
                    cv.create_text(x + 19, 106, text=self.digitado[i], font=f(24, "bold"))
            if len(self.digitado) == 2:
                voto = self.urna.classificar_voto(self.digitado)
                if voto == NULO:
                    cv.create_text(16, 158, text="NÚMERO ERRADO", anchor="w", font=f(16, "bold"))
                    cv.create_text(16, 190, text="VOTO NULO", anchor="w",
                                   font=f(24, "bold"), fill=C["vermelho"])
                else:
                    c = self.urna.candidatos[voto]
                    avatar(cv, W - 68, 122, 44, c.nome, cor_de(voto))
                    cv.create_text(16, 166, text=f"Nome:  {c.nome}", anchor="w", font=f(13))
                    cv.create_text(16, 192, text=f"Partido:  {c.partido}", anchor="w", font=f(13))

        if self.digitado == BRANCO or len(self.digitado) == 2:
            cv.create_line(0, H - 80, W, H - 80, fill="#999")
            cv.create_text(16, H - 64, text="Aperte a tecla:", anchor="w", font=f(10, "bold"))
            cv.create_text(28, H - 43, text="VERDE para CONFIRMAR este voto", anchor="w", font=f(10))
            cv.create_text(28, H - 22, text="LARANJA para REINICIAR este voto", anchor="w", font=f(10))

    # ---------- ações do mesário ----------
    def registrar(self, msg, tag="info"):
        hora = datetime.now().strftime("%H:%M:%S")
        self.log.config(state="normal")
        self.log.insert("end", f"[{hora}] {msg}\n", tag)
        self.log.see("end")
        self.log.config(state="disabled")

    def _selecionou(self, _):
        sel = self.tree.selection()
        if sel:
            self.v_tit.set(sel[0])

    def _piscar_erro(self):
        self.ent_tit.config(bg="#f8c9c4")
        self.after(500, lambda: self.ent_tit.config(bg="white"))

    def liberar(self):
        if self.simulando:
            return
        tit = self.v_tit.get().strip()
        if self.titulo_atual:
            self.registrar("Já existe um eleitor na cabine. Aguarde o voto terminar.", "erro")
            return
        try:
            nome = self.urna.liberar_eleitor(tit)
        except (PermissionError, DatabaseError) as e:
            self.registrar(f"✖ {e} (título {mascarar(tit) or 'vazio'})", "erro")
            self._piscar_erro()
            return
        self.titulo_atual, self.digitado, self.estado = tit, "", "votando"
        self.lbl_cabine.config(text=f"Na cabine: {nome}", fg=C["verde"])
        self.registrar(f"Eleitor(a) liberado(a): {nome} ({mascarar(tit)})", "ok")
        self.v_tit.set("")
        self.focus_set()
        self.desenhar_tela()
        self.atualizar_progresso()

    # ---------- teclas da urna ----------
    def _teclado(self, e):
        try:
            if self.focus_get() is self.ent_tit:
                if e.keysym in ("Return", "KP_Enter"):
                    self.liberar()
                return
        except KeyError:
            return
        if self.simulando or not self.titulo_atual:
            return
        if e.char and e.char.isdigit():
            self.digito(e.char)
        elif e.keysym in ("Return", "KP_Enter"):
            self.confirma()
        elif e.keysym in ("BackSpace", "Escape"):
            self.corrige()
        elif e.char.lower() == "b":
            self.branco()

    def digito(self, d):
        if self.estado == "votando" and not self.simulando \
                and self.digitado != BRANCO and len(self.digitado) < 2:
            self.digitado += d
            self.desenhar_tela()

    def branco(self):
        if self.estado == "votando" and not self.simulando and self.digitado == "":
            self.digitado = BRANCO
            self.desenhar_tela()

    def corrige(self):
        if self.estado == "votando" and not self.simulando:
            self.digitado = ""
            self.desenhar_tela()

    def confirma(self, simulado=False):
        if self.estado != "votando" or (self.simulando and not simulado):
            return
        if not (self.digitado == BRANCO or len(self.digitado) == 2):
            return
        tit = self.titulo_atual
        try:
            self.urna.registrar_voto(tit, self.digitado)
        except (PermissionError, DatabaseError):
            self.registrar("Falha ao registrar o voto. A participação não foi alterada.", "erro")
            self._piscar_erro()
            return False
        self.app.bell()
        self.tree.item(tit, values=(tit, self.urna.eleitores_aptos[tit], "✔ votou"), tags=("votou",))
        self.tree.see(tit)
        self.registrar(f"Voto computado · hash {self.urna.cadeia[-1]['hash'][:16]}…", "ok")
        self.titulo_atual, self.digitado, self.estado = None, "", "fim"
        self.lbl_cabine.config(text="Cabine livre", fg=C["cinza"])
        self.desenhar_tela()
        self.atualizar_progresso()
        if not simulado:
            self.after(1300, self._apos_fim)
        return True

    def _apos_fim(self):
        if self.estado == "fim":
            self.estado = "aguardando"
            self.desenhar_tela()
        if len(self.urna.ja_votaram) == len(self.urna.eleitores_aptos):
            self.registrar("Todos os eleitores da seção já votaram.", "info")

    def atualizar_progresso(self):
        n, tot = len(self.urna.cadeia), len(self.urna.eleitores_aptos)
        self.pb["value"] = n
        falta = max(0, MIN_VOTOS - n)
        extra = (f"faltam {falta} para o mínimo de {MIN_VOTOS}" if falta
                 else "mínimo atingido ✔")
        self.lbl_prog.config(text=f"Votos computados: {n} de {tot}   ·   {extra}")
        livre = not self.simulando and not self.titulo_atual
        self.b_enc.set_ativo(n >= MIN_VOTOS and livre)
        self.b_sim.set_ativo(n < tot and livre)

    # ---------- simulação ----------
    def simular(self):
        restantes = [t for t in self.urna.eleitores_aptos if t not in self.urna.ja_votaram]
        if not restantes or self.titulo_atual:
            return
        nums = list(self.urna.candidatos)
        faixa = (10, 35) if self.urna.turno == 1 else (40, 60)
        opcoes = nums + [BRANCO, NULO]
        pesos = [random.randint(*faixa) for _ in nums] + [4, 4]
        self.simulando = True
        self.atualizar_progresso()
        self.registrar(f"Simulação iniciada para {len(restantes)} eleitor(es).", "info")
        self._sim_passo(restantes, opcoes, pesos, 0)

    def _sim_passo(self, fila, opcoes, pesos, i):
        if i >= len(fila):
            self.simulando = False
            self.estado = "aguardando"
            self.desenhar_tela()
            self.atualizar_progresso()
            self.registrar("Simulação concluída. Todos votaram.", "info")
            return
        tit = fila[i]
        try:
            self.urna.liberar_eleitor(tit)
        except (PermissionError, DatabaseError):
            self.simulando = False
            self.atualizar_progresso()
            self.registrar("A simulação foi interrompida por uma falha de persistência.", "erro")
            return
        self.titulo_atual, self.estado = tit, "votando"
        self.digitado = random.choices(opcoes, weights=pesos)[0]
        self.desenhar_tela()
        self.after(220, lambda: self._sim_confirma(fila, opcoes, pesos, i))

    def _sim_confirma(self, fila, opcoes, pesos, i):
        if not self.confirma(simulado=True):
            self.simulando = False
            self.estado = "aguardando"
            self.titulo_atual = None
            self.atualizar_progresso()
            return
        if (i + 1) % 4 == 0:  # alguém tenta votar de novo
            tit = fila[i]
            try:
                self.urna.liberar_eleitor(tit)
            except PermissionError:
                self.registrar(f"✖ Tentativa de voto duplo bloqueada ({mascarar(tit)})", "erro")
        self.after(180, lambda: self._sim_passo(fila, opcoes, pesos, i + 1))

    # ---------- encerramento ----------
    def encerrar(self):
        n = len(self.urna.cadeia)
        if n < MIN_VOTOS:
            return messagebox.showwarning("Ainda não", f"São necessários pelo menos {MIN_VOTOS} votos.")
        faltam = len(self.urna.eleitores_aptos) - n
        if faltam and not messagebox.askyesno(
                "Encerrar votação", f"{faltam} eleitor(es) ainda não votaram.\nEncerrar mesmo assim?"):
            return
        try:
            self.urna.encerrar()
        except (PermissionError, RuntimeError, DatabaseError) as e:
            return messagebox.showerror("Não foi possível encerrar", str(e))
        self.app.mostrar(TelaResultado, urna=self.urna)


# ---------------------------------------------------------------------------
# Tela 3 — Apuração
# ---------------------------------------------------------------------------
class TelaResultado(tk.Frame):
    def __init__(self, master, app, urna: Urna):
        super().__init__(master, bg=C["fundo"])
        self.app, self.urna = app, urna
        self.ok = urna.verificar_integridade()
        if self.ok:
            r = urna.apurar()
        else:
            r = {"ranking": [], "validos": 0, "brancos": 0, "nulos": 0,
                 "total": len(urna.cadeia), "comparecimento": len(urna.ja_votaram),
                 "aptos": len(urna.eleitores_aptos)}
        self.r = r
        self.dec = decidir(urna, r) if self.ok else dict(tipo="sem", nota="",
                                                         detalhe="Urna adulterada: apuração anulada.")
        mun = urna.municipio

        dir_ = tk.Frame(self, bg=C["fundo"])
        dir_.pack(side="right", fill="y")
        esq = tk.Frame(self, bg=C["fundo"])
        esq.pack(side="left", fill="both", expand=True, padx=(0, 12))

        # --- gráfico ---
        g = card(esq, f"Boletim de Urna · {urna.turno}º turno · {mun.nome}")
        g.pack(fill="both", expand=True)
        regra = ("maioria absoluta dos votos válidos" if mun.exige_maioria_absoluta and urna.turno == 1
                 else "2º turno" if urna.turno == 2 else "maioria simples (turno único)")
        tk.Label(g, text=f"Eleitorado do município: {mun.eleitorado:,}".replace(",", ".")
                 + f"   ·   Regra: {regra}   ·   % sobre votos válidos",
                 bg="white", fg=C["cinza"], font=f(10)).pack(anchor="w", padx=14)
        self.cv = tk.Canvas(g, bg="white", highlightthickness=0)
        self.cv.pack(fill="both", expand=True, padx=14, pady=10)

        # --- números ---
        st = tk.Frame(esq, bg=C["fundo"])
        st.pack(fill="x", pady=(12, 0))
        comp = r["comparecimento"]
        for i, (rot, val) in enumerate([
                ("Aptos", r["aptos"]),
                ("Comparecimento", f"{comp} ({comp / r['aptos']:.0%})"),
                ("Abstenções", r["aptos"] - comp),
                ("Válidos", r["validos"]),
                ("Brancos", r["brancos"]),
                ("Nulos", r["nulos"])]):
            box = card(st)
            box.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0))
            st.columnconfigure(i, weight=1)
            tk.Label(box, text=str(val), bg="white", fg=C["texto"], font=f(16, "bold")).pack(pady=(10, 0))
            tk.Label(box, text=rot, bg="white", fg=C["cinza"], font=f(9)).pack(pady=(0, 10))

        # --- resultado ---
        self._card_resultado(dir_)

        # --- integridade ---
        ig = tk.Frame(dir_, bg="#e7f6ec" if self.ok else "#fdecea",
                      highlightbackground=C["borda"], highlightthickness=1)
        ig.pack(fill="x", pady=12)
        tk.Label(ig, text="✔ Cadeia de votos íntegra" if self.ok else "✖ CADEIA VIOLADA",
                 bg=ig["bg"], fg=C["verde"] if self.ok else C["vermelho"],
                 font=f(11, "bold")).pack(anchor="w", padx=12, pady=(10, 2))
        tk.Label(ig, text=f"SHA-256 é uma demonstração didática de detecção de alterações; "
                          f"não impede adulteração por quem controla e recalcula os dados.\n"
                          f"{len(urna.cadeia)} registros · {comp} eleitores que votaram.\nHash final:",
                 bg=ig["bg"], fg=C["texto"], font=f(9), justify="left").pack(anchor="w", padx=12)
        hash_final = urna.cadeia[-1]["hash"] if urna.cadeia else "-"
        tk.Label(ig, text=hash_final, bg=ig["bg"], fg=C["texto"], font=("Courier", 8),
                 wraplength=330, justify="left").pack(anchor="w", padx=12, pady=(0, 10))

        acoes = tk.Frame(dir_, bg=C["fundo"])
        acoes.pack(fill="x")
        Botao(acoes, "Salvar boletim (.txt)", self.salvar, bg=C["cinza"]).pack(side="left")
        Botao(acoes, "Nova eleição", lambda: app.mostrar(TelaConfig), bg=C["azul"]).pack(side="right")

        self.after(80, self.desenhar_grafico)

    def _card_resultado(self, master):
        d = self.dec
        cores = {"eleito": "#e7f6ec", "segundo": "#fff4d6", "sem": "#f3f4f6"}
        rc = tk.Frame(master, bg=cores[d["tipo"]], highlightbackground=C["borda"],
                      highlightthickness=1, width=370)
        rc.pack(fill="x")
        bg = rc["bg"]

        def lbl(texto, fonte, cor=C["texto"], **kw):
            tk.Label(rc, text=texto, bg=bg, fg=cor, font=fonte, wraplength=340,
                     justify="left").pack(anchor="w", padx=14, **kw)

        if d["tipo"] == "eleito":
            c = self.urna.candidatos[d["eleito"]]
            lbl("🏆 ELEITO(A) PREFEITO(A)", f(11, "bold"), C["verde"], pady=(12, 2))
            lbl(c.nome, f(20, "bold"))
            lbl(f"{c.numero} · {c.partido}", f(11), C["cinza"])
            lbl(d["detalhe"], f(10), pady=(8, 0))
        elif d["tipo"] == "segundo":
            a, b = (self.urna.candidatos[n] for n in d["finalistas"])
            lbl("HAVERÁ 2º TURNO", f(11, "bold"), "#7a5200", pady=(12, 2))
            lbl(f"{a.nome}\n×  {b.nome}", f(15, "bold"))
            lbl(d["detalhe"], f(10), pady=(8, 0))
        else:
            lbl("SEM VENCEDOR", f(11, "bold"), C["vermelho"], pady=(12, 2))
            lbl(d["detalhe"], f(10))
        if d.get("nota"):
            lbl("⚖ " + d["nota"], f(9), C["cinza"], pady=(6, 0))

        if d["tipo"] == "segundo":
            sep = tk.Frame(rc, bg="#e9d9a8", height=1)
            sep.pack(fill="x", padx=14, pady=10)
            lbl("Antes do 2º turno houve morte, desistência ou impedimento legal de algum finalista?",
                f(9), C["texto"])
            opcoes = ["Nenhum impedimento"] + [f"{n} · {self.urna.candidatos[n].nome}"
                                               for n in d["finalistas"]]
            self.cb = ttk.Combobox(rc, values=opcoes, state="readonly", width=40)
            self.cb.current(0)
            self.cb.pack(anchor="w", padx=14, pady=6)
            Botao(rc, "Iniciar 2º turno  ▶", self.iniciar_2t, bg=C["verde"]) \
                .pack(fill="x", padx=14, pady=(4, 14))
        else:
            tk.Frame(rc, bg=bg, height=12).pack()

    def iniciar_2t(self):
        escolha = self.cb.get()
        impedido = None if self.cb.current() == 0 else escolha.split(" · ")[0]
        try:
            urna2, aviso = montar_segundo_turno(self.urna, self.dec["finalistas"], impedido)
        except (ValueError, RuntimeError) as e:
            return messagebox.showerror("Segundo turno indisponível", str(e))
        self.app.mostrar(TelaVotacao, urna=urna2, aviso=aviso)

    def desenhar_grafico(self, passo=0):
        cv = self.cv
        if not cv.winfo_exists():
            return
        cv.delete("all")
        W, H = max(cv.winfo_width(), 500), max(cv.winfo_height(), 300)
        rk = self.r["ranking"]
        validos = self.r["validos"] or 1
        frac = min(1.0, passo / 24)
        frac = 1 - (1 - frac) ** 3  # desacelera no final
        x0, maxw = 96, W - 96 - 150
        rowh = max(58, min(86, (H - 40) / max(1, len(rk))))
        topo = 26

        mun = self.urna.municipio
        if mun.exige_maioria_absoluta and self.urna.turno == 1:
            xm = x0 + maxw * 0.5
            yb = topo + rowh * len(rk) - 6
            cv.create_line(xm, topo + 22, xm, yb, dash=(4, 3), fill="#9ca3af")
            cv.create_text(xm, yb + 4, text="50% dos válidos", anchor="n", fill=C["cinza"], font=f(8))

        d = self.dec
        for i, (num, votos) in enumerate(rk):
            c = self.urna.candidatos[num]
            y = topo + i * rowh
            cor = cor_de(num) if c.apto else "#9ca3af"
            avatar(cv, 44, y + 20, 26, c.nome, cor)
            cv.create_text(x0, y, text=f"{num} · {c.nome}", anchor="w", font=f(12, "bold"), fill=C["texto"])
            selo = ""
            if d["tipo"] == "eleito" and num == d["eleito"]:
                selo, cor_selo = "★ ELEITO(A)", C["verde"]
            elif d["tipo"] == "segundo" and num in d["finalistas"]:
                selo, cor_selo = "→ 2º TURNO", "#b7791f"
            if not c.apto:
                selo, cor_selo = "IMPEDIDO(A)", C["vermelho"]
            if selo:
                larg = len(f"{num} · {c.nome}") * 8 + 14
                cv.create_text(x0 + larg, y, text=selo, anchor="w", font=f(9, "bold"), fill=cor_selo)
            cv.create_text(x0, y + 17, text=c.partido, anchor="w", font=f(9), fill=C["cinza"])
            cv.create_rectangle(x0, y + 28, x0 + maxw, y + 46, fill="#eef1f5", outline="")
            w = maxw * (votos / validos) * frac
            if w > 0:
                cv.create_rectangle(x0, y + 28, x0 + w, y + 46, fill=cor, outline="")
            cv.create_text(x0 + w + 8, y + 37, anchor="w", font=f(10, "bold"), fill=C["texto"],
                           text=f"{round(votos * frac)} votos · {votos / validos * frac:.1%}")
        if passo < 24:
            self.after(30, lambda: self.desenhar_grafico(passo + 1))

    def salvar(self):
        u, r, d = self.urna, self.r, self.dec
        caminho = filedialog.asksaveasfilename(
            defaultextension=".txt", initialfile=f"boletim_{u.turno}turno.txt",
            filetypes=[("Texto", "*.txt")])
        if not caminho:
            return
        linhas = [
            f"BOLETIM DE URNA — {u.turno}º TURNO",
            f"Município: {u.municipio.nome} | Eleitorado: {u.municipio.eleitorado}",
            f"Emitido em: {datetime.now():%d/%m/%Y %H:%M:%S}",
            "-" * 50,
        ]
        for num, votos in r["ranking"]:
            c = u.candidatos[num]
            pct = votos / r["validos"] if r["validos"] else 0
            linhas.append(f"{num}  {c.nome:<28} {c.partido:<6} {votos:>4}  {pct:6.1%}")
        linhas += [
            "-" * 50,
            f"Válidos: {r['validos']}  Brancos: {r['brancos']}  Nulos: {r['nulos']}  "
            f"Total: {r['total']}  Aptos: {r['aptos']}",
            f"Integridade: {'OK' if self.ok else 'VIOLADA'}",
            f"Hash final: {u.cadeia[-1]['hash'] if u.cadeia else '-'}",
            f"Resultado: {d['detalhe']} {d.get('nota', '')}".strip(),
        ]
        with open(caminho, "w", encoding="utf-8") as arq:
            arq.write("\n".join(linhas) + "\n")
        messagebox.showinfo("Boletim salvo", f"Arquivo salvo em:\n{caminho}")


if __name__ == "__main__":
    App().mainloop()
