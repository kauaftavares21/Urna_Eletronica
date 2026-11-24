# Simulador didático de urna eletrônica

Aplicação acadêmica em Python para simular uma eleição municipal. O projeto tem
uma interface gráfica Tkinter, um modo de terminal, persistência local SQLite,
apuração dos votos e uma cadeia SHA-256 usada em exercícios de integridade.

> **Uso exclusivamente didático.** Este programa não é uma urna oficial, não é
> certificado e não deve ser utilizado para conduzir eleições reais.

## Índice

- [O que o programa faz](#o-que-o-programa-faz)
- [Regras da simulação](#regras-da-simulação)
- [Requisitos](#requisitos)
- [Instalação e execução no Windows](#instalação-e-execução-no-windows)
- [Como usar a interface gráfica](#como-usar-a-interface-gráfica)
- [Como usar o terminal](#como-usar-o-terminal)
- [Persistência e recuperação](#persistência-e-recuperação)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Como os módulos se relacionam](#como-os-módulos-se-relacionam)
- [Esquema do banco](#esquema-do-banco)
- [Privacidade e integridade dos votos](#privacidade-e-integridade-dos-votos)
- [Testes](#testes)
- [Solução de problemas](#solução-de-problemas)

## O que o programa faz

- Configura municípios de exemplo ou informa um município para a simulação.
- Cadastra candidatos com número, nome, partido e data de nascimento.
- Gera eleitores e títulos **fictícios** para uma seção simulada.
- Permite votação interativa pela interface Tkinter ou pelo terminal.
- Oferece uma votação automática para demonstrações e testes.
- Bloqueia eleitor não cadastrado, voto duplicado e tentativa de voto após o
  encerramento.
- Apura votos nominais, brancos e nulos e apresenta o resultado e o boletim.
- Persiste eleições e turnos em SQLite, para consulta após fechar e reabrir o
  programa.
- Permite abrir uma eleição salva pela opção **Consultar eleições salvas** na
  interface gráfica.

## Regras da simulação

- Até 200.000 eleitores no município: vence o candidato apto com mais votos,
  conforme a regra didática de turno único.
- Mais de 200.000 eleitores no município: exige maioria absoluta dos votos
  válidos; se ninguém superar 50%, os dois primeiros seguem para o segundo
  turno.
- Votos brancos e nulos não entram no total de votos válidos.
- Empates no ranking são ordenados pela idade do candidato; o candidato mais
  idoso fica à frente.
- A seção simulada pode ter menos eleitores que o eleitorado total do
  município, mas nunca pode excedê-lo. O limite de 200.000 se refere ao
  eleitorado municipal, não à quantidade de eleitores cadastrados na seção.
- O segundo turno reutiliza o cadastro de eleitores, mas começa com participação
  e cadeia de votos próprias. Cada eleitor pode votar uma vez em cada turno.

Essas regras são simplificações educacionais implementadas pelo projeto. Os
municípios e eleitorados dos presets são exemplos didáticos, não dados oficiais.

## Requisitos

- Windows 10 ou mais recente (outros sistemas podem funcionar com Python e
  Tkinter instalados).
- Python 3.10 ou superior.
- A interface gráfica requer Tcl/Tk, normalmente incluído na distribuição
  oficial do Python para Windows.
- Não é necessário instalar servidor de banco ou pacote Python adicional. O
  SQLite é acessado pelo módulo `sqlite3` da biblioteca padrão.

## Instalação e execução no Windows

1. Instale Python 3.10+ e habilite a opção de adicionar Python ao `PATH`.
2. Abra PowerShell e entre na pasta do projeto:

   ```powershell
   cd "$env:USERPROFILE\Desktop\Urna_Eletronica"
   ```

3. Confirme a versão do Python:

   ```powershell
   python --version
   ```

4. Inicie a interface gráfica ou o terminal:

   ```powershell
   python visual_urna.py
   ```

   ```powershell
   python urna_eletronica.py
   ```

Os dois arquivos na raiz são lançadores compatíveis. A implementação fica no
pacote `urna_app`. O caminho do banco é calculado em relação aos arquivos do
projeto, portanto os comandos também podem ser iniciados a partir de outro
diretório, por exemplo:

```powershell
python "C:\caminho\Urna_Eletronica\visual_urna.py"
```

## Como usar a interface gráfica

1. Escolha um preset didático ou informe o município e o eleitorado total.
2. Revise os candidatos de exemplo, adicione candidatos ou remova os que não
   deseja usar. É preciso ter ao menos dois candidatos.
3. Informe a quantidade de eleitores fictícios da seção. O mínimo para encerrar
   a votação é 10.
4. Clique em **Iniciar votação** e escolha a votação interativa ou use o botão
   de simulação na tela de votação.
5. Na votação interativa, o mesário libera um eleitor cadastrado; o eleitor
   informa o número do candidato, confirma, corrige ou vota em branco.
6. Depois de atingir o mínimo de votos, encerre a votação para ver o boletim.
   Eleitores restantes podem se abster.
7. Se a regra e o resultado exigirem segundo turno, use o controle apresentado
   para manter os finalistas ou simular o impedimento de um deles.
8. Abra **Consultar eleições salvas** para consultar uma eleição encerrada ou
   retomar uma votação que ainda esteja aberta.

## Como usar o terminal

Execute `python urna_eletronica.py` e siga as perguntas. Escolha o modo interativo
ou automático, o município, os candidatos e o tamanho da seção. No modo
interativo, a aplicação mostra os títulos fictícios gerados para que possam ser
informados pelo mesário durante a simulação.

O modo automático também simula tentativas de voto duplicado, que devem ser
bloqueadas. Se houver segundo turno, o programa reutiliza a seção e coleta uma
nova sequência de votos.

## Persistência e recuperação

O banco é criado automaticamente no primeiro uso, em:

```text
data/urna_eletronica.db
```

Esse caminho não depende do diretório de trabalho atual. Eleições diferentes
recebem registros próprios; iniciar outra eleição não apaga as anteriores. O
histórico da interface mostra cada turno como um registro, e o segundo turno
aponta para o primeiro por `eleicao_pai_id`.

Os cadastros são recuperados ao abrir uma eleição salva. Uma votação em
andamento pode ser retomada; uma votação encerrada abre o boletim em modo de
consulta. O banco usa `PRAGMA user_version` para identificar a versão do esquema
e não substitui automaticamente um banco existente.

### Backup e restauração

1. Feche o programa para evitar cópia durante uma gravação.
2. Copie `data/urna_eletronica.db` para um local seguro, como outro disco ou uma
   pasta de backup.
3. Para restaurar, feche o programa e coloque a cópia de volta nesse mesmo
   caminho.

O arquivo pode ser consultado com uma ferramenta compatível com SQLite. Evite
editar registros manualmente: alterações podem invalidar a cadeia de hashes ou
as relações entre tabelas.

## Estrutura do projeto

```text
Urna_Eletronica/
├── data/
│   ├── .gitkeep
│   └── urna_eletronica.db       # criado em execução; não deve ir para o Git
├── tests/
│   ├── test_database.py         # testes de persistência e transações
│   └── test_urna_eletronica.py  # testes das regras da urna
├── urna_app/
│   ├── __init__.py              # API pública do pacote
│   ├── core.py                  # modelos e regras de negócio
│   ├── database.py              # esquema e operações SQLite
│   ├── terminal.py              # interface e fluxo de terminal
│   └── gui.py                   # interface Tkinter
├── database.py                 # compatibilidade com imports antigos
├── urna_eletronica.py           # lançador do modo de terminal
├── visual_urna.py               # lançador da interface gráfica
├── README.md
└── .gitignore
```

O banco de execução e os arquivos temporários do Python são ignorados pelo Git.
Os testes criam bancos descartáveis em diretórios temporários e não alteram os
dados da aplicação.

## Como os módulos se relacionam

```text
visual_urna.py ──> urna_app.gui ──────┐
                                      ├──> urna_app.core.Urna ──> database.Database ──> SQLite
urna_eletronica.py ──> urna_app.terminal ┘
```

- **`urna_app.core`** contém `Candidato`, `Municipio`, `Urna` e regras de
  classificação, votação, segundo turno e apuração. Não depende da interface.
- **`urna_app.database`** centraliza SQL, transações, criação de tabelas,
  auditoria e verificação dos registros persistidos.
- **`urna_app.terminal`** contém perguntas, mensagens e o fluxo interativo ou
  automático de terminal. Ele usa a mesma classe `Urna` que a GUI.
- **`urna_app.gui`** apresenta as telas Tkinter e chama a lógica da `Urna`; não
  mantém uma implementação paralela das regras eleitorais.
- **Lançadores na raiz** preservam os nomes de arquivo e comandos usados em
  versões anteriores.
- **`tests/`** verifica regras, esquema, rollback, recuperação, segundo turno e
  integridade usando bancos temporários.

As conexões SQLite são abertas por operação, ativam chaves estrangeiras e são
fechadas ao final. Operações compostas, como registrar um voto e a participação
correspondente, usam uma única transação.

## Esquema do banco

| Tabela | Conteúdo e relação |
|---|---|
| `municipios` | Município, eleitorado total, indicador de capital e criação. |
| `eleicoes` | Um registro por turno, status, datas e ligação opcional com o turno anterior. |
| `candidatos` | Candidatos por turno; o número é único dentro da eleição/turno. |
| `eleitores` | Identificador SHA-256 do título fictício e nome fictício. |
| `eleitores_eleicao` | Eleitores habilitados e participação separada por turno. |
| `votos` | Sequência, escolha, elo anterior, hash atual e horário; sem ID de eleitor. |
| `auditoria` | Eventos administrativos, como criação, impedimento e encerramento. |

As chaves estrangeiras são ativadas em cada conexão. Restrições `UNIQUE`, `CHECK`
e índices protegem a estrutura e aceleram consultas comuns. Todas as entradas
em SQL são passadas como parâmetros.

## Privacidade e integridade dos votos

Os títulos criados pelo aplicativo são fictícios. Para que o mesário possa
recuperar a seção após reiniciar, o banco guarda o valor fictício exibido e seu
SHA-256. **Não cadastre nem use títulos reais.**

A tabela `eleitores_eleicao` registra somente se a pessoa fictícia votou. A
tabela `votos` não guarda título, ID de eleitor ou chave que permita ligar uma
participação a uma escolha. A participação e o voto são atualizados na mesma
transação, sem criar essa associação.

Cada hash de voto é calculado sobre JSON canônico UTF-8, com chaves ordenadas e
separadores fixos, contendo:

- ID da eleição/turno;
- sequência do registro;
- código do voto (número, `BRANCO` ou `NULO`);
- hash anterior;
- horário UTC do registro.

Na verificação, o programa recalcula a cadeia, procura quebras de sequência e
elo, compara os registros persistidos com os dados usados pela urna e confere a
quantidade de votos com a participação registrada. Isso ajuda a demonstrar
detecção de alterações comuns. Não impede adulteração por alguém que controle o
arquivo e o código e possa recalcular os hashes; SQLite e SHA-256 aqui não são
uma proteção eleitoral certificada.

## Testes

No PowerShell, execute a partir da raiz do projeto:

```powershell
$env:PYTHONUTF8 = "1"
python -m unittest discover -s tests -v
```

O `PYTHONUTF8` evita problemas de exibição de caracteres acentuados em alguns
terminais Windows. Os testes cobrem persistência e reabertura, votos nominais,
brancos e nulos, duplicidades, encerramento, rollback, segundo turno, chaves
estrangeiras, parametrização SQL e adulteração da cadeia.

Para verificar a sintaxe de todos os módulos:

```powershell
python -m py_compile database.py urna_eletronica.py visual_urna.py urna_app\__init__.py urna_app\core.py urna_app\database.py urna_app\terminal.py urna_app\gui.py tests\test_database.py tests\test_urna_eletronica.py
```

## Solução de problemas

### `python` não é reconhecido

Instale Python para Windows e marque **Add Python to PATH**; depois abra um novo
PowerShell e tente `python --version`.

### A interface não inicia ou informa que não encontrou `init.tcl`

Essa mensagem normalmente indica uma instalação de Python sem Tcl/Tk disponível.
Use o instalador oficial do Python para Windows com o componente Tcl/Tk ou
repare a instalação. O modo de terminal não depende de Tkinter:

```powershell
python urna_eletronica.py
```

### Quero começar uma eleição nova

Use **Nova eleição** ou volte à tela de configuração. Os registros anteriores
permanecem no histórico. Para remover dados, faça isso somente depois de fechar
o programa e guardar um backup do banco.
