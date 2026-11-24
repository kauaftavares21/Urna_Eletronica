"""Camada SQLite da simulação. Não associa identidade de eleitor ao voto."""
from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


DB_PATH = Path(__file__).resolve().parent.parent / "data" / "urna_eletronica.db"
ZERO_HASH = "0" * 64
MIN_VOTOS = 10


class DatabaseError(RuntimeError):
    """Falha compreensível de persistência, sem detalhes internos do SQLite."""


class Database:
    def __init__(self, caminho: str | Path | None = None):
        self._uri = False
        self._anchor = None
        self._closed = False
        if caminho is not None and str(caminho) == ":memory:":
            self.caminho = f"file:urna_{uuid.uuid4().hex}?mode=memory&cache=shared"
            self._uri = True
            self._anchor = sqlite3.connect(self.caminho, uri=True)
            self._anchor.execute("PRAGMA foreign_keys = ON")
        else:
            self.caminho = Path(caminho) if caminho is not None else DB_PATH
        self.inicializar_banco()

    @contextmanager
    def _conectar(self) -> Iterator[sqlite3.Connection]:
        if self._closed:
            raise DatabaseError("Esta instância do banco já foi fechada.")
        conexao = None
        try:
            conexao = sqlite3.connect(str(self.caminho), timeout=10, uri=self._uri)
            conexao.row_factory = sqlite3.Row
            conexao.execute("PRAGMA foreign_keys = ON")
        except sqlite3.Error as erro:
            if conexao is not None:
                conexao.close()
            raise DatabaseError("Não foi possível abrir o banco SQLite.") from erro
        try:
            yield conexao
            conexao.commit()
        except sqlite3.Error as erro:
            conexao.rollback()
            raise DatabaseError("Falha ao acessar os dados persistidos.") from erro
        except BaseException:
            conexao.rollback()
            raise
        finally:
            conexao.close()

    def inicializar_banco(self) -> None:
        if not self._uri:
            try:
                self.caminho.parent.mkdir(parents=True, exist_ok=True)
            except OSError as erro:
                raise DatabaseError("Não foi possível criar a pasta de dados da aplicação.") from erro
        self.criar_tabelas()

    def close(self) -> None:
        """Fecha o ponto de retenção de um banco em memória compartilhado."""
        if self._anchor is not None:
            self._anchor.close()
            self._anchor = None
        self._closed = True

    def criar_tabelas(self) -> None:
        with self._conectar() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS municipios (
                    id INTEGER PRIMARY KEY,
                    nome TEXT NOT NULL,
                    eleitorado INTEGER NOT NULL CHECK(eleitorado > 0),
                    capital INTEGER NOT NULL DEFAULT 0 CHECK(capital IN (0, 1)),
                    criado_em TEXT NOT NULL,
                    UNIQUE(nome, eleitorado, capital)
                );
                CREATE TABLE IF NOT EXISTS eleicoes (
                    id INTEGER PRIMARY KEY,
                    municipio_id INTEGER NOT NULL REFERENCES municipios(id),
                    eleicao_pai_id INTEGER REFERENCES eleicoes(id),
                    turno INTEGER NOT NULL CHECK(turno IN (1, 2)),
                    status TEXT NOT NULL CHECK(status IN ('configurada', 'em_votacao', 'encerrada')),
                    criada_em TEXT NOT NULL,
                    encerrada_em TEXT,
                    UNIQUE(eleicao_pai_id, turno)
                );
                CREATE TABLE IF NOT EXISTS candidatos (
                    id INTEGER PRIMARY KEY,
                    eleicao_id INTEGER NOT NULL REFERENCES eleicoes(id),
                    numero TEXT NOT NULL CHECK(length(numero) = 2),
                    nome TEXT NOT NULL,
                    partido TEXT NOT NULL,
                    nascimento TEXT NOT NULL,
                    apto INTEGER NOT NULL CHECK(apto IN (0, 1)),
                    UNIQUE(eleicao_id, numero)
                );
                CREATE TABLE IF NOT EXISTS eleitores (
                    id INTEGER PRIMARY KEY,
                    titulo_hash TEXT NOT NULL UNIQUE,
                    titulo_ficticio TEXT NOT NULL UNIQUE,
                    nome TEXT NOT NULL,
                    criado_em TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS eleitores_eleicao (
                    eleicao_id INTEGER NOT NULL REFERENCES eleicoes(id),
                    eleitor_id INTEGER NOT NULL REFERENCES eleitores(id),
                    ja_votou INTEGER NOT NULL DEFAULT 0 CHECK(ja_votou IN (0, 1)),
                    votou_em TEXT,
                    PRIMARY KEY(eleicao_id, eleitor_id)
                );
                CREATE TABLE IF NOT EXISTS votos (
                    id INTEGER PRIMARY KEY,
                    eleicao_id INTEGER NOT NULL REFERENCES eleicoes(id),
                    sequencia INTEGER NOT NULL CHECK(sequencia > 0),
                    voto TEXT NOT NULL,
                    hash_anterior TEXT NOT NULL,
                    hash_atual TEXT NOT NULL,
                    registrado_em TEXT NOT NULL,
                    UNIQUE(eleicao_id, sequencia)
                );
                CREATE TABLE IF NOT EXISTS auditoria (
                    id INTEGER PRIMARY KEY,
                    eleicao_id INTEGER REFERENCES eleicoes(id),
                    evento TEXT NOT NULL,
                    detalhes TEXT NOT NULL DEFAULT '',
                    criado_em TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_eleicoes_data ON eleicoes(criada_em);
                CREATE INDEX IF NOT EXISTS idx_votos_eleicao ON votos(eleicao_id, sequencia);
                CREATE INDEX IF NOT EXISTS idx_auditoria_eleicao ON auditoria(eleicao_id, criado_em);
            """)
            versao = db.execute("PRAGMA user_version").fetchone()[0]
            if versao == 0:
                db.execute("PRAGMA user_version = 1")
            elif versao > 1:
                raise DatabaseError("A versão do banco é mais nova que a suportada por esta aplicação.")

    @staticmethod
    def _agora() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="microseconds")

    @staticmethod
    def _hash_titulo(titulo: str) -> str:
        return hashlib.sha256(titulo.encode("utf-8")).hexdigest()

    def salvar_municipio(self, municipio) -> int:
        with self._conectar() as db:
            db.execute("INSERT OR IGNORE INTO municipios(nome, eleitorado, capital, criado_em) VALUES (?, ?, ?, ?)",
                       (municipio.nome, municipio.eleitorado, int(municipio.capital), self._agora()))
            return db.execute("SELECT id FROM municipios WHERE nome=? AND eleitorado=? AND capital=?",
                              (municipio.nome, municipio.eleitorado, int(municipio.capital))).fetchone()[0]

    def obter_municipio(self, municipio_id: int) -> dict | None:
        with self._conectar() as db:
            row = db.execute("SELECT * FROM municipios WHERE id=?", (municipio_id,)).fetchone()
            return dict(row) if row else None

    def salvar_eleicao(self, municipio_id: int, turno: int = 1, eleicao_pai_id: int | None = None) -> int:
        if turno not in (1, 2):
            raise ValueError("O turno deve ser 1 ou 2.")
        if turno == 1 and eleicao_pai_id is not None:
            raise ValueError("O primeiro turno não pode ter eleição pai.")
        with self._conectar() as db:
            if turno == 2:
                pai = db.execute("SELECT municipio_id, turno, status FROM eleicoes WHERE id=?", (eleicao_pai_id,)).fetchone()
                if (not pai or pai["turno"] != 1 or pai["status"] != "encerrada"
                        or pai["municipio_id"] != municipio_id):
                    raise ValueError("O segundo turno deve estar ligado ao primeiro turno encerrado do mesmo município.")
            cur = db.execute("INSERT INTO eleicoes(municipio_id, eleicao_pai_id, turno, status, criada_em) "
                             "VALUES (?, ?, ?, 'configurada', ?)",
                             (municipio_id, eleicao_pai_id, turno, self._agora()))
            eid = cur.lastrowid
            self.registrar_evento_auditoria("eleicao_criada", f"turno={turno}", eid, conexao=db)
            return eid

    def criar_segundo_turno(self, primeiro_turno_id: int, candidatos: list) -> int:
        """Cria o turno filho e copia finalistas/eleitores em uma transação só."""
        with self._conectar() as db:
            primeiro = db.execute("SELECT municipio_id, turno, status FROM eleicoes WHERE id=?",
                                  (primeiro_turno_id,)).fetchone()
            if not primeiro or primeiro["turno"] != 1 or primeiro["status"] != "encerrada":
                raise ValueError("O primeiro turno precisa estar encerrado para criar o segundo.")
            if len(candidatos) != 2 or any(not c.apto for c in candidatos):
                raise ValueError("O segundo turno precisa de dois candidatos aptos.")
            cur = db.execute("INSERT INTO eleicoes(municipio_id, eleicao_pai_id, turno, status, criada_em) "
                             "VALUES (?, ?, 2, 'configurada', ?)",
                             (primeiro["municipio_id"], primeiro_turno_id, self._agora()))
            segundo_id = cur.lastrowid
            db.executemany("INSERT INTO candidatos(eleicao_id, numero, nome, partido, nascimento, apto) "
                           "VALUES (?, ?, ?, ?, ?, ?)",
                           [(segundo_id, c.numero, c.nome, c.partido, c.nascimento.isoformat(), int(c.apto))
                            for c in candidatos])
            db.execute("INSERT INTO eleitores_eleicao(eleicao_id, eleitor_id, ja_votou, votou_em) "
                        "SELECT ?, eleitor_id, 0, NULL FROM eleitores_eleicao WHERE eleicao_id=?",
                        (segundo_id, primeiro_turno_id))
            self.registrar_evento_auditoria("segundo_turno_criado", "Finalistas e seção copiados", segundo_id,
                                            conexao=db)
            return segundo_id

    def obter_eleicao(self, eleicao_id: int) -> dict | None:
        with self._conectar() as db:
            row = db.execute("SELECT e.*, m.nome municipio_nome, m.eleitorado municipio_eleitorado, "
                             "m.capital municipio_capital FROM eleicoes e JOIN municipios m ON m.id=e.municipio_id "
                             "WHERE e.id=?", (eleicao_id,)).fetchone()
            return dict(row) if row else None

    def listar_eleicoes(self) -> list[dict]:
        with self._conectar() as db:
            rows = db.execute("SELECT e.id, e.eleicao_pai_id, e.turno, e.status, e.criada_em, e.encerrada_em, "
                               "m.nome municipio, m.eleitorado, (SELECT count(*) FROM votos v WHERE v.eleicao_id=e.id) votos "
                               "FROM eleicoes e JOIN municipios m ON m.id=e.municipio_id ORDER BY e.id DESC").fetchall()
            return [dict(r) for r in rows]

    def salvar_candidato(self, eleicao_id: int, candidato) -> None:
        with self._conectar() as db:
            self._garantir_configuravel(db, eleicao_id)
            db.execute("INSERT INTO candidatos(eleicao_id, numero, nome, partido, nascimento, apto) "
                       "VALUES (?, ?, ?, ?, ?, ?)",
                       (eleicao_id, candidato.numero, candidato.nome, candidato.partido,
                        candidato.nascimento.isoformat(), int(candidato.apto)))

    def atualizar_aptidao(self, eleicao_id: int, numero: str, apto: bool) -> None:
        with self._conectar() as db:
            self._garantir_configuravel(db, eleicao_id)
            db.execute("UPDATE candidatos SET apto=? WHERE eleicao_id=? AND numero=?",
                       (int(apto), eleicao_id, numero))

    def registrar_impedimento(self, eleicao_id: int, numero: str) -> None:
        """Registra impedimento superveniente de candidato após o 1º turno."""
        with self._conectar() as db:
            row = db.execute("SELECT turno, status FROM eleicoes WHERE id=?", (eleicao_id,)).fetchone()
            if not row or row["turno"] != 1 or row["status"] != "encerrada":
                raise ValueError("Impedimento só pode ser registrado para finalista do primeiro turno.")
            cur = db.execute("UPDATE candidatos SET apto=0 WHERE eleicao_id=? AND numero=?", (eleicao_id, numero))
            if cur.rowcount != 1:
                raise ValueError("Candidato não encontrado no primeiro turno.")
            self.registrar_evento_auditoria("candidato_impedido", f"numero={numero}", eleicao_id, conexao=db)

    def listar_candidatos(self, eleicao_id: int) -> list[dict]:
        with self._conectar() as db:
            return [dict(r) for r in db.execute("SELECT * FROM candidatos WHERE eleicao_id=? ORDER BY numero",
                                                 (eleicao_id,)).fetchall()]

    def salvar_eleitor(self, eleicao_id: int, titulo: str, nome: str) -> None:
        digest = self._hash_titulo(titulo)
        with self._conectar() as db:
            self._garantir_configuravel(db, eleicao_id)
            db.execute("INSERT OR IGNORE INTO eleitores(titulo_hash, titulo_ficticio, nome, criado_em) VALUES (?, ?, ?, ?)",
                       (digest, titulo, nome, self._agora()))
            eleitor = db.execute("SELECT id FROM eleitores WHERE titulo_hash=?", (digest,)).fetchone()
            db.execute("INSERT INTO eleitores_eleicao(eleicao_id, eleitor_id) VALUES (?, ?)",
                       (eleicao_id, eleitor[0]))

    def listar_eleitores(self, eleicao_id: int) -> list[dict]:
        with self._conectar() as db:
            rows = db.execute("SELECT e.titulo_ficticio titulo, e.nome, ee.ja_votou, ee.votou_em "
                               "FROM eleitores_eleicao ee JOIN eleitores e ON e.id=ee.eleitor_id "
                               "WHERE ee.eleicao_id=? ORDER BY e.id", (eleicao_id,)).fetchall()
            return [dict(r) for r in rows]

    def eleitor_votou(self, eleicao_id: int, titulo: str) -> bool:
        with self._conectar() as db:
            row = db.execute("SELECT ee.ja_votou FROM eleitores_eleicao ee JOIN eleitores e ON e.id=ee.eleitor_id "
                             "WHERE ee.eleicao_id=? AND e.titulo_hash=?",
                             (eleicao_id, self._hash_titulo(titulo))).fetchone()
            return bool(row and row[0])

    @staticmethod
    def _garantir_aberta(db: sqlite3.Connection, eleicao_id: int) -> sqlite3.Row:
        row = db.execute("SELECT status FROM eleicoes WHERE id=?", (eleicao_id,)).fetchone()
        if not row:
            raise ValueError("Eleição não encontrada.")
        if row["status"] == "encerrada":
            raise PermissionError("Eleição encerrada; alterações bloqueadas.")
        return row

    @staticmethod
    def _garantir_configuravel(db: sqlite3.Connection, eleicao_id: int) -> sqlite3.Row:
        row = Database._garantir_aberta(db, eleicao_id)
        if row["status"] != "configurada":
            raise PermissionError("O cadastro está bloqueado porque a votação já começou.")
        return row

    def _marcar_participacao(self, db: sqlite3.Connection, eleicao_id: int, titulo_hash: str, agora: str) -> None:
        cur = db.execute("UPDATE eleitores_eleicao SET ja_votou=1, votou_em=? WHERE eleicao_id=? AND eleitor_id="
                         "(SELECT id FROM eleitores WHERE titulo_hash=?) AND ja_votou=0",
                         (agora, eleicao_id, titulo_hash))
        if cur.rowcount != 1:
            raise PermissionError("Eleitor não cadastrado neste turno ou já votou.")

    def registrar_voto(self, eleicao_id: int, turno: int, titulo: str, voto: str) -> dict:
        titulo_hash = self._hash_titulo(titulo)
        try:
            with self._conectar() as db:
                self._garantir_aberta(db, eleicao_id)
                eleitor = db.execute("SELECT ee.ja_votou FROM eleitores_eleicao ee JOIN eleitores e ON e.id=ee.eleitor_id "
                                     "WHERE ee.eleicao_id=? AND e.titulo_hash=?",
                                     (eleicao_id, titulo_hash)).fetchone()
                if not eleitor:
                    raise PermissionError("Eleitor não cadastrado neste turno.")
                if eleitor["ja_votou"]:
                    raise PermissionError("ELEITOR JÁ VOTOU! Tentativa de voto duplo bloqueada.")
                eleicao = db.execute("SELECT turno FROM eleicoes WHERE id=?", (eleicao_id,)).fetchone()
                if not eleicao or eleicao["turno"] != turno:
                    raise ValueError("Turno incompatível com a eleição persistida.")
                if voto not in ("BRANCO", "NULO"):
                    c = db.execute("SELECT apto FROM candidatos WHERE eleicao_id=? AND numero=?",
                                   (eleicao_id, voto)).fetchone()
                    if not c or not c["apto"]:
                        raise ValueError("O candidato não está apto neste turno.")
                anterior_row = db.execute("SELECT sequencia, hash_atual FROM votos WHERE eleicao_id=? "
                                          "ORDER BY sequencia DESC LIMIT 1", (eleicao_id,)).fetchone()
                sequencia = (anterior_row["sequencia"] + 1) if anterior_row else 1
                anterior = anterior_row["hash_atual"] if anterior_row else ZERO_HASH
                agora = self._agora()
                canonico = json.dumps({"eleicao_id": eleicao_id, "turno": turno, "sequencia": sequencia,
                                       "voto": voto, "hash_anterior": anterior, "registrado_em": agora},
                                      sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                atual = hashlib.sha256(canonico.encode("utf-8")).hexdigest()
                db.execute("INSERT INTO votos(eleicao_id, sequencia, voto, hash_anterior, hash_atual, registrado_em) "
                           "VALUES (?, ?, ?, ?, ?, ?)", (eleicao_id, sequencia, voto, anterior, atual, agora))
                self._marcar_participacao(db, eleicao_id, titulo_hash, agora)
                db.execute("UPDATE eleicoes SET status='em_votacao' WHERE id=?", (eleicao_id,))
                return {"sequencia": sequencia, "voto": voto, "hash_anterior": anterior,
                        "hash_atual": atual, "registrado_em": agora}
        except sqlite3.Error as erro:
            raise DatabaseError("Não foi possível registrar o voto; a operação foi desfeita.") from erro

    @staticmethod
    def _hash_voto(eleicao_id: int, turno: int, voto: str, sequencia: int,
                   hash_anterior: str, registrado_em: str) -> str:
        canonico = json.dumps({"eleicao_id": eleicao_id, "turno": turno, "sequencia": sequencia,
                               "voto": voto, "hash_anterior": hash_anterior, "registrado_em": registrado_em},
                              sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonico.encode("utf-8")).hexdigest()

    def listar_votos_para_apuracao(self, eleicao_id: int) -> list[dict]:
        with self._conectar() as db:
            return [dict(r) for r in db.execute("SELECT sequencia, voto, hash_anterior, hash_atual, registrado_em "
                                                 "FROM votos WHERE eleicao_id=? ORDER BY sequencia", (eleicao_id,)).fetchall()]

    def _verificar_integridade_conexao(self, db: sqlite3.Connection, eleicao_id: int) -> bool:
        eleicao = db.execute("SELECT turno FROM eleicoes WHERE id=?", (eleicao_id,)).fetchone()
        if not eleicao:
            return False
        votos = db.execute("SELECT sequencia, voto, hash_anterior, hash_atual, registrado_em "
                           "FROM votos WHERE eleicao_id=? ORDER BY sequencia", (eleicao_id,)).fetchall()
        anterior = ZERO_HASH
        for i, row in enumerate(votos, 1):
            if row["sequencia"] != i or row["hash_anterior"] != anterior:
                return False
            esperado = self._hash_voto(eleicao_id, eleicao["turno"], row["voto"], i,
                                       anterior, row["registrado_em"])
            if not isinstance(row["hash_atual"], str) or not hmac.compare_digest(esperado, row["hash_atual"]):
                return False
            anterior = row["hash_atual"]
        participantes = db.execute("SELECT count(*) FROM eleitores_eleicao WHERE eleicao_id=? AND ja_votou=1",
                                   (eleicao_id,)).fetchone()[0]
        return len(votos) == participantes

    def verificar_integridade(self, eleicao_id: int) -> bool:
        try:
            with self._conectar() as db:
                return self._verificar_integridade_conexao(db, eleicao_id)
        except (DatabaseError, KeyError, TypeError, ValueError, sqlite3.Error):
            return False

    def encerrar_eleicao(self, eleicao_id: int) -> None:
        with self._conectar() as db:
            row = db.execute("SELECT status FROM eleicoes WHERE id=?", (eleicao_id,)).fetchone()
            if not row:
                raise ValueError("Eleição não encontrada.")
            if row["status"] == "encerrada":
                return
            quantidade = db.execute("SELECT count(*) FROM votos WHERE eleicao_id=?", (eleicao_id,)).fetchone()[0]
            if quantidade < MIN_VOTOS:
                raise PermissionError(f"São necessários pelo menos {MIN_VOTOS} votos para encerrar.")
            if not self._verificar_integridade_conexao(db, eleicao_id):
                raise RuntimeError("A cadeia persistida está inconsistente; eleição não pode ser encerrada.")
            db.execute("UPDATE eleicoes SET status='encerrada', encerrada_em=? WHERE id=?",
                       (self._agora(), eleicao_id))
            self.registrar_evento_auditoria("eleicao_encerrada", "", eleicao_id, conexao=db)

    def registrar_evento_auditoria(self, evento: str, detalhes: str = "", eleicao_id: int | None = None,
                                    conexao: sqlite3.Connection | None = None) -> None:
        if conexao is not None:
            conexao.execute("INSERT INTO auditoria(eleicao_id, evento, detalhes, criado_em) VALUES (?, ?, ?, ?)",
                            (eleicao_id, evento, detalhes, self._agora()))
            return
        with self._conectar() as db:
            db.execute("INSERT INTO auditoria(eleicao_id, evento, detalhes, criado_em) VALUES (?, ?, ?, ?)",
                       (eleicao_id, evento, detalhes, self._agora()))

    def obter_resultados(self, eleicao_id: int) -> dict:
        if not self.verificar_integridade(eleicao_id):
            raise RuntimeError("Cadeia de votos inválida; resultados não podem ser considerados válidos.")
        candidatos = {r["numero"]: 0 for r in self.listar_candidatos(eleicao_id)}
        brancos = nulos = 0
        for row in self.listar_votos_para_apuracao(eleicao_id):
            if row["voto"] == "BRANCO":
                brancos += 1
            elif row["voto"] == "NULO":
                nulos += 1
            elif row["voto"] in candidatos:
                candidatos[row["voto"]] += 1
        return {"candidatos": candidatos, "brancos": brancos, "nulos": nulos,
                "total": sum(candidatos.values()) + brancos + nulos}

    def verificar_chaves_estrangeiras(self) -> list[tuple]:
        with self._conectar() as db:
            return [tuple(r) for r in db.execute("PRAGMA foreign_key_check").fetchall()]
