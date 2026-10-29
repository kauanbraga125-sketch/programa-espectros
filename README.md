# IMESPEC 1.5.0

Programa desktop de análise Raman do projeto de iniciação científica de Kauan.
Esta versão traz a nova tela de espectros em **Qt/PySide6**, com organização inspirada no Origin,
e conserva o módulo Raman Map com mapas de áreas e razão A/B.

Na versão **1.5.0**, a tela **Data Quality** foi reorganizada: mapa, espectro do ponto e controles
de correção ficam juntos. Abrir a aba carrega as ferramentas do mapa ativo; o seletor Mapa troca
a banda sem perder as correções das demais. Os cálculos existentes foram preservados.

## Instalar no Windows

1. Abra [Actions → IMESPEC para Windows](https://github.com/kauanbraga125-sketch/programa-espectros/actions/workflows/windows.yml).
2. Abra a execução mais recente que terminou com sucesso.
3. Em **Artifacts**, baixe **IMESPEC-1.5.0-Instalador-Windows**.
4. Extraia o ZIP e execute **IMESPEC-1.5.0-Setup.exe**.

O instalador inclui o Python e as dependências necessárias. Não é preciso instalar Python à parte.
A instalação é feita para o usuário atual, com atalho no menu Iniciar e opção de atalho na área de trabalho.
O programa funciona localmente, sem conexão para analisar seus arquivos.

Para usar sem instalar, baixe o artefato **Portatil-Windows**, extraia o pacote interno
e abra `IMESPEC.exe` dentro da pasta completa. Mantenha a pasta `_internal` junto do executável.

O primeiro build precisa terminar para os arquivos aparecerem. Os artefatos ficam disponíveis por 90 dias;
uma nova execução do workflow gera novos pacotes.

## Usar a cascata

1. Clique em **Abrir espectros** e selecione os TXT/CSV da sua série.
2. A cascata 2D aparece com espaçamento automático. A temperatura é sugerida quando o nome contém um número seguido de **K**.
3. Confira os valores na lista. Selecione uma curva para editar seu rótulo, temperatura ou cor.
4. Marque/desmarque curvas para mostrar/ocultar. Arraste os nomes ou use ↑/↓ para reorganizar.
5. Use **Salvar projeto** para continuar depois ou **Exportar figura** para salvar PNG, PDF ou SVG.

Também há os modos **Sobrepor** e **Waterfall 3D**. No 3D, a profundidade representa a temperatura
quando todas são conhecidas e distintas; caso contrário, representa a ordem dos espectros.
O espaçamento automático e os rótulos são o padrão. **Mais opções** contém o alinhamento opcional por um ponto Raman.

Janelas espectrais sem sobreposição são separadas no seletor **Região espectral**.
Curvas com faixas diferentes mantêm somente os pontos que foram medidos; não são interpoladas nem completadas.
Nos dados Cn-MWNT, abra os TXT após extrair o ZIP. NGS binário não é um formato de entrada desta versão.

### Dados e unidades

- Eixo espectral: Raman shift em **cm⁻¹**; intensidade em **a.u.**; temperatura em **K**.
- Cascata: o programa soma constantes somente às curvas exibidas. Não normaliza, suaviza ou corrige o fundo automaticamente.
- O alinhamento opcional muda a altura de exibição; não move os picos ao longo do eixo Raman.
- **Arquivo → Exportar dados** inclui intensidade original, intensidade exibida e deslocamento visual em colunas separadas.
- O projeto `.imespec` guarda os dados originais e as configurações; não depende de os arquivos permanecerem na mesma pasta.

Leia [Como funciona a cascata](docs/CASCATA.md) para as convenções numéricas.

## Raman Map

Clique em **Raman Map** para abrir o módulo existente. Nesta etapa da migração, ele conserva sua interface Tkinter.
A nova janela fica oculta durante seu uso e volta quando o módulo é fechado ou você escolhe Início/Multi-Spectra.
A série da cascata permanece carregada.

Os mapas de bandas, a inspeção por pixel, a revisão da integração, as correções e a razão entre áreas A/B
continuam disponíveis. **Exporte os mapas antes de sair desse módulo:** salvar projeto na nova tela salva apenas a série de espectros.
Os eixos dos mapas permanecem em pixels até recuperarmos a calibração espacial da aquisição.

Leia [Fluxo do Raman Map](docs/RAMAN_MAP.md).

## Executar pelo código

Use Python 3.10 ou posterior; o build usa Python 3.12.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements.txt
python IMESPEC.py
```

No Linux, o módulo Raman Map também requer o pacote Tk do sistema (por exemplo, `python3-tk`).
A entrada principal é **IMESPEC.py**. `Imespec1.py` é a implementação preservada do workspace anterior.

## Testes e build

```bash
python -m unittest discover -s tests -v
python IMESPEC.py --smoke-test
```

O workflow do Windows testa os cálculos e a tela Qt, gera o executável com PyInstaller,
abre os dois módulos empacotados e verifica instalação, abertura e desinstalação.
Depois disponibiliza o instalador, a versão portátil e seus hashes SHA-256.

Arquitetura e limites estão em [docs/ARQUITETURA.md](docs/ARQUITETURA.md).
Os dados experimentais e os projetos pessoais não são enviados para este repositório.


## Análise de picos (1.5.0)

Use **Análise > Ajustar picos e sobretons** ou **Analisar picos** para estimar
centros, larguras, áreas e comparações entre ordens. Perfis Lorentziana,
Gaussiana e Pseudo-Voigt, fundo simultâneo, resíduos, bootstrap opcional e
exportação JSON/CSV. Dados originais preservados; atribuições e resposta
instrumental exigem revisão. Leia [o método e os limites](docs/ANALISE_DE_PICOS.md).
