"""Testes de regressão reproduzíveis para a simulação didática."""
import unittest
import tempfile
from pathlib import Path
from datetime import date, timedelta
from unittest.mock import patch

import urna_eletronica as ue
from database import Database

_TEST_DB = None


def nova_urna(eleitorado=250_000, qtd=10, banco=None):
    urna = ue.Urna(ue.Municipio("Município de teste", eleitorado), banco=banco or _TEST_DB)
    hoje = date.today()
    for numero, idade in (("12", 65), ("25", 55), ("33", 45)):
        urna.cadastrar_candidato(ue.Candidato(numero, f"Pessoa {numero}", "ABC",
                                               date(hoje.year - idade, 1, 1)))
    for i in range(qtd):
        urna.registrar_eleitor(f"{i + 1:012d}", f"Eleitor {i + 1}")
    return urna


def votar(urna, votos):
    for (titulo, _), escolha in zip(urna.eleitores_aptos.items(), votos):
        urna.registrar_voto(titulo, escolha)


class TestUrna(unittest.TestCase):
    def setUp(self):
        global _TEST_DB
        self.temp = tempfile.TemporaryDirectory()
        _TEST_DB = Database(Path(self.temp.name) / "teste.db")

    def tearDown(self):
        self.temp.cleanup()

    def test_cadastro_candidato_valido(self):
        urna = nova_urna()
        self.assertIn("12", urna.candidatos)

    def test_numero_invalido(self):
        with self.assertRaises(ValueError):
            nova_urna().cadastrar_candidato(ue.Candidato("1", "Nome", "ABC", date(1980, 1, 1)))

    def test_candidato_duplicado(self):
        with self.assertRaises(ValueError):
            nova_urna().cadastrar_candidato(ue.Candidato("12", "Outro", "ABC", date(1980, 1, 1)))

    def test_dados_candidato_invalidos(self):
        urna = nova_urna()
        for c in (ue.Candidato("88", "", "ABC", date(1980, 1, 1)),
                  ue.Candidato("88", "Nome", "", date(1980, 1, 1)),
                  ue.Candidato("88", "Nome", "ABC", date.today() + timedelta(days=1))):
            with self.subTest(c=c), self.assertRaises(ValueError):
                urna.cadastrar_candidato(c)

    def test_eleitores_sem_titulos_duplicados(self):
        urna = nova_urna(qtd=0)
        with patch.object(ue.random, "randint", side_effect=[100000000000, 100000000000, 100000000001]):
            titulos = ue.gerar_eleitores(urna, 2)
        self.assertEqual(len(titulos), len(set(titulos)))

    def test_eleitor_nao_cadastrado(self):
        with self.assertRaises(PermissionError):
            nova_urna().liberar_eleitor("999999999999")

    def test_voto_duplicado_bloqueado(self):
        urna = nova_urna()
        urna.registrar_voto("000000000001", "12")
        with self.assertRaises(PermissionError):
            urna.registrar_voto("000000000001", "25")

    def test_voto_apos_encerrar_bloqueado(self):
        urna = nova_urna()
        votar(urna, ["12"] * 10)
        urna.encerrar()
        with self.assertRaises(PermissionError):
            urna.registrar_voto("000000000001", "12")

    def test_classificacao_nominal_branco_nulo(self):
        urna = nova_urna()
        self.assertEqual(urna.classificar_voto("12"), "12")
        self.assertEqual(urna.classificar_voto(ue.BRANCO), ue.BRANCO)
        self.assertEqual(urna.classificar_voto("99"), ue.NULO)

    def test_apuracao_nominais_brancos_nulos(self):
        urna = nova_urna()
        votar(urna, ["12", "12", "25", ue.BRANCO, "99"] + ["33"] * 5)
        r = urna.apurar()
        self.assertEqual((r["validos"], r["brancos"], r["nulos"]), (8, 1, 1))
        self.assertEqual(dict(r["ranking"]), {"12": 2, "25": 1, "33": 5})

    def test_porcentagem_sobre_validos(self):
        urna = nova_urna()
        votar(urna, ["12"] * 5 + ["25"] * 4 + [ue.BRANCO])
        r = urna.apurar()
        self.assertEqual(r["ranking"][0][1] / r["validos"], 5 / 9)

    def test_desempate_por_idade(self):
        urna = nova_urna()
        votar(urna, ["12"] * 5 + ["25"] * 5)
        self.assertEqual(urna.apurar()["ranking"][0][0], "12")

    def test_sem_votos_validos(self):
        urna = nova_urna()
        votar(urna, [ue.BRANCO, "99"] * 5)
        self.assertEqual(urna.apurar()["validos"], 0)
        self.assertIsNone(ue.resultado(urna, urna.apurar()))

    def test_votacao_automatica_aceita_opcao_nula_sem_numero_reservado(self):
        urna = nova_urna()
        with patch.object(ue.random, "choices", side_effect=[[ue.NULO] for _ in range(10)]), \
                patch.object(ue.time, "sleep"):
            ue.sessao_de_votacao_automatica(urna, {ue.NULO: 1})
        self.assertEqual(urna.apurar()["nulos"], 10)

    def test_vitoria_maioria_absoluta(self):
        urna = nova_urna()
        votar(urna, ["12"] * 6 + ["25"] * 4)
        self.assertIsNone(ue.resultado(urna, urna.apurar()))

    def test_necessidade_segundo_turno(self):
        urna = nova_urna()
        votar(urna, ["12"] * 5 + ["25"] * 5)
        self.assertEqual(len(ue.resultado(urna, urna.apurar())), 2)

    def test_prepara_segundo_turno_isolado_e_eleitores_reusados(self):
        urna = nova_urna()
        votar(urna, ["12"] * 5 + ["25"] * 5)
        urna.encerrar()
        urna2 = ue.preparar_segundo_turno(urna, ["12", "25"], None)
        self.assertEqual(urna2.eleitores_aptos, urna.eleitores_aptos)
        self.assertEqual(urna2.cadeia, [])
        self.assertIsNot(urna2.cadeia, urna.cadeia)

    def test_substitui_finalista_impedido(self):
        urna = nova_urna()
        votar(urna, ["12"] * 5 + ["25"] * 3 + ["33"] * 2)
        urna.encerrar()
        urna2 = ue.preparar_segundo_turno(urna, ["12", "25"], "12")
        self.assertEqual(set(urna2.candidatos), {"25", "33"})
        self.assertFalse(urna.candidatos["12"].apto)

    def test_sem_substituto_ou_finalistas_validos(self):
        urna = nova_urna()
        urna.banco.atualizar_aptidao(urna.eleicao_id, "33", False)
        urna.candidatos["33"].apto = False
        votar(urna, ["12"] * 5 + ["25"] * 5)
        urna.encerrar()
        with self.assertRaises(ValueError):
            ue.preparar_segundo_turno(urna, ["12", "25"], "12")

    def test_detecta_alteracao_cadeia(self):
        urna = nova_urna()
        votar(urna, ["12"] * 10)
        urna.cadeia[0]["voto"] = "25"
        self.assertFalse(urna.verificar_integridade())
        with self.assertRaises(RuntimeError):
            urna.apurar()

    def test_detecta_inconsistencia_votantes(self):
        urna = nova_urna()
        votar(urna, ["12"])
        urna.ja_votaram.clear()
        self.assertFalse(urna.verificar_integridade())

    def test_registro_incompleto_e_colecao_invalida_sao_rejeitados(self):
        urna = nova_urna()
        urna.cadeia.append({"voto": "12"})
        self.assertFalse(urna.verificar_integridade())
        urna.cadeia = None
        self.assertFalse(urna.verificar_integridade())

    def test_encerramento_insuficiente(self):
        urna = nova_urna()
        votar(urna, ["12"] * 9)
        with self.assertRaises(PermissionError):
            urna.encerrar()

    def test_quantidade_limite_municipal(self):
        urna = nova_urna(eleitorado=10, qtd=0)
        with self.assertRaises(ValueError):
            ue.gerar_eleitores(urna, 11)
        self.assertFalse(ue.Municipio("Capital", 200_000, True).exige_maioria_absoluta)
        self.assertTrue(ue.Municipio("Município", 200_001).exige_maioria_absoluta)

    def test_quantidade_eleitores_invalida(self):
        for valor in (0, -1, 1.5, True):
            with self.subTest(valor=valor), self.assertRaises(ValueError):
                ue.gerar_eleitores(nova_urna(qtd=0), valor)


if __name__ == "__main__":
    unittest.main()
