"""Testes de persistência SQLite usando arquivos temporários isolados."""
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import urna_eletronica as ue
from database import Database
from database import DatabaseError


def raw_db(path):
    """Contexto de teste que também fecha a conexão (sqlite3 with não fecha)."""
    class ClosedConnection:
        def __enter__(self):
            self.conn = sqlite3.connect(path)
            return self.conn

        def __exit__(self, kind, value, traceback):
            if kind:
                self.conn.rollback()
            else:
                self.conn.commit()
            self.conn.close()
    return ClosedConnection()


class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "test.db"
        self.db = Database(self.path)
        self.urna = ue.Urna(ue.Municipio("Cidade teste", 300_000), banco=self.db)
        for num, year in (("12", 1960), ("25", 1970), ("33", 1980)):
            self.urna.cadastrar_candidato(ue.Candidato(num, f"Candidato {num}", "ABC", date(year, 1, 1)))
        for i in range(10):
            self.urna.registrar_eleitor(f"{i + 1:012d}", f"Eleitor {i + 1}")

    def tearDown(self):
        self.temp.cleanup()

    def vote(self, urn, choices):
        for (title, _), choice in zip(urn.eleitores_aptos.items(), choices):
            urn.registrar_voto(title, choice)

    def test_01_cria_banco_tabelas_e_versao(self):
        with raw_db(self.path) as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue({"municipios", "eleicoes", "candidatos", "eleitores",
                             "eleitores_eleicao", "votos", "auditoria"} <= tables)
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 1)

    def test_02_municipio_recuperado(self):
        mun = self.db.obter_municipio(self.urna.municipio_id)
        self.assertEqual((mun["nome"], mun["eleitorado"]), ("Cidade teste", 300_000))

    def test_03_candidatos_recuperados(self):
        self.assertEqual(len(self.db.listar_candidatos(self.urna.eleicao_id)), 3)

    def test_04_numero_candidato_duplicado_no_turno(self):
        with self.assertRaises(ValueError):
            self.urna.cadastrar_candidato(ue.Candidato("12", "Duplicado", "XYZ", date(1985, 1, 1)))

    def test_05_eleitores_ficticios_recuperados(self):
        self.assertEqual(len(self.db.listar_eleitores(self.urna.eleicao_id)), 10)
        with raw_db(self.path) as conn:
            raw = conn.execute("SELECT titulo_hash, titulo_ficticio FROM eleitores LIMIT 1").fetchone()
        self.assertEqual(len(raw[0]), 64)
        self.assertTrue(raw[1].isdigit())

    def test_06_eleitor_duplicado_no_turno(self):
        with self.assertRaises(ValueError):
            self.urna.registrar_eleitor("000000000001", "Duplicado")

    def test_07_voto_nominal_persistido(self):
        self.urna.registrar_voto("000000000001", "12")
        self.assertEqual(self.db.listar_votos_para_apuracao(self.urna.eleicao_id)[0]["voto"], "12")
        self.assertTrue(self.db.eleitor_votou(self.urna.eleicao_id, "000000000001"))

    def test_08_voto_branco_e_nulo(self):
        self.urna.registrar_voto("000000000001", ue.BRANCO)
        self.urna.registrar_voto("000000000002", "99")
        result = self.db.obter_resultados(self.urna.eleicao_id)
        self.assertEqual((result["brancos"], result["nulos"]), (1, 1))

    def test_09_voto_duplicado_bloqueado(self):
        self.urna.registrar_voto("000000000001", "12")
        with self.assertRaises(PermissionError):
            self.urna.registrar_voto("000000000001", "25")

    def test_10_voto_apos_encerramento_bloqueado(self):
        self.vote(self.urna, ["12"] * 10)
        self.urna.encerrar()
        with self.assertRaises(PermissionError):
            self.urna.registrar_voto("000000000001", "12")

    def test_11_rollback_se_falha_ao_marcar_participacao(self):
        with patch.object(self.db, "_marcar_participacao", side_effect=RuntimeError("falha simulada")):
            with self.assertRaises(RuntimeError):
                self.urna.registrar_voto("000000000001", "12")
        self.assertEqual(self.db.listar_votos_para_apuracao(self.urna.eleicao_id), [])
        self.assertFalse(self.db.eleitor_votou(self.urna.eleicao_id, "000000000001"))

    def test_12_dados_sobrevivem_a_reabertura(self):
        self.urna.registrar_voto("000000000001", "12")
        db2 = Database(self.path)
        reaberta = ue.Urna.carregar(db2, self.urna.eleicao_id)
        self.assertEqual(len(reaberta.cadeia), 1)
        self.assertIn("12", reaberta.candidatos)
        self.assertIn("000000000001", reaberta.ja_votaram)

    def test_13_resultados_recuperados(self):
        self.vote(self.urna, ["12"] * 6 + ["25"] * 3 + [ue.BRANCO])
        self.assertEqual(self.db.obter_resultados(self.urna.eleicao_id)["candidatos"]["12"], 6)

    def test_14_hash_verificavel_apos_reabrir(self):
        self.vote(self.urna, ["12"] * 10)
        reaberta = ue.Urna.carregar(Database(self.path), self.urna.eleicao_id)
        self.assertTrue(reaberta.verificar_integridade())

    def test_15_alteracao_ou_remocao_detectadas(self):
        self.vote(self.urna, ["12"] * 10)
        with raw_db(self.path) as conn:
            conn.execute("UPDATE votos SET voto='25' WHERE eleicao_id=? AND sequencia=1", (self.urna.eleicao_id,))
        self.assertFalse(self.urna.verificar_integridade())
        with self.assertRaises(RuntimeError):
            self.db.obter_resultados(self.urna.eleicao_id)
        with raw_db(self.path) as conn:
            conn.execute("DELETE FROM votos WHERE eleicao_id=? AND sequencia=10", (self.urna.eleicao_id,))
        self.assertFalse(self.urna.verificar_integridade())

    def test_16_primeiro_turno_preservado_no_segundo(self):
        self.vote(self.urna, ["12"] * 5 + ["25"] * 5)
        self.urna.encerrar()
        before = self.db.listar_votos_para_apuracao(self.urna.eleicao_id)
        urna2 = ue.preparar_segundo_turno(self.urna, ["12", "25"], None)
        urna2.registrar_voto("000000000001", "25")
        self.assertEqual(before, self.db.listar_votos_para_apuracao(self.urna.eleicao_id))

    def test_17_participacao_independente_por_turno(self):
        self.vote(self.urna, ["12"] * 5 + ["25"] * 5)
        self.urna.encerrar()
        urna2 = ue.preparar_segundo_turno(self.urna, ["12", "25"], None)
        urna2.registrar_voto("000000000001", "25")
        self.assertEqual(len(urna2.ja_votaram), 1)
        self.assertEqual(len(self.urna.ja_votaram), 10)
        with raw_db(self.path) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(votos)")}
        self.assertFalse(columns & {"eleitor_id", "titulo", "titulo_hash"})

    def test_18_historico_anterior_recuperavel(self):
        older_id = self.urna.eleicao_id
        other = ue.Urna(ue.Municipio("Outra cidade", 90_000), banco=self.db)
        ids = {r["id"] for r in self.db.listar_eleicoes()}
        self.assertEqual(ids, {older_id, other.eleicao_id})

    def test_19_chaves_estrangeiras_ativas(self):
        self.assertEqual(self.db.verificar_chaves_estrangeiras(), [])
        with self.assertRaises(DatabaseError):
            self.db.salvar_eleicao(999999)

    def test_20_entradas_sao_parametrizadas(self):
        ataque = "Cidade'); DROP TABLE candidatos; --"
        municipio = ue.Municipio(ataque, 50_000)
        mid = self.db.salvar_municipio(municipio)
        self.assertEqual(self.db.obter_municipio(mid)["nome"], ataque)
        self.assertEqual(len(self.db.listar_candidatos(self.urna.eleicao_id)), 3)

    def test_21_segundo_turno_e_copias_sao_atomicos(self):
        self.vote(self.urna, ["12"] * 5 + ["25"] * 5)
        self.urna.encerrar()
        finalistas = [self.urna.candidatos[n] for n in ("12", "25")]
        with patch.object(self.db, "registrar_evento_auditoria", side_effect=RuntimeError("falha simulada")):
            with self.assertRaises(RuntimeError):
                self.db.criar_segundo_turno(self.urna.eleicao_id, finalistas)
        self.assertEqual(len(self.db.listar_eleicoes()), 1)
        second_id = self.db.criar_segundo_turno(self.urna.eleicao_id, finalistas)
        self.assertEqual(len(self.db.listar_candidatos(second_id)), 2)
        self.assertEqual(len(self.db.listar_eleitores(second_id)), 10)

    def test_22_cadastro_fica_bloqueado_apos_inicio_da_votacao(self):
        self.urna.registrar_voto("000000000001", "12")
        with self.assertRaises(PermissionError):
            self.urna.cadastrar_candidato(ue.Candidato("88", "Novo", "ABC", date(1985, 1, 1)))
        with self.assertRaises(PermissionError):
            self.urna.registrar_eleitor("999999999999", "Novo eleitor")

    def test_23_banco_em_memoria_compartilhado_e_fechavel(self):
        memory = Database(":memory:")
        municipality = ue.Municipio("Memória", 10)
        municipality_id = memory.salvar_municipio(municipality)
        self.assertEqual(memory.obter_municipio(municipality_id)["nome"], "Memória")
        memory.close()
        with self.assertRaises(DatabaseError):
            memory.obter_municipio(municipality_id)


if __name__ == "__main__":
    unittest.main()
