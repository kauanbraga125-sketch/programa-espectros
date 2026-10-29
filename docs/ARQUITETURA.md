# Arquitetura 1.4.1

| Arquivo | Responsabilidade |
|---|---|
| `IMESPEC.py` | Entrada única do código e do executável; seleciona Qt ou o módulo de mapas. |
| `imespec_app/window.py` | Interface Qt, navegação, worker, gráficos, projetos e exportação. |
| `imespec_app/spectra.py` | Espectros somente leitura, importação, grupos, deslocamentos e persistência. Sem GUI. |
| `Imespec1.py` | Workspace Tkinter preservado; no modo de compatibilidade, Início/Multi-Spectra retorna ao Qt. |
| `imespec_maps.py` | Coleção de mapas e razões, inspeção e exportação; conecta a nova tela Data Quality aos mesmos cálculos. |
| `imespec_quality.py` | Layout responsivo e controles nativos para Data Quality; delega a ciência ao núcleo existente. |
| `imespec_analysis.py` | Razões de áreas, validade e prévia numérica da integração. Preservado. |
| `imespec_bib1.py` | Núcleo existente de análise e ferramentas de mapas. Preservado. |
| `packaging/` | PyInstaller, instalador Inno Setup, ícone e smoke tests do executável. |

## Migração gradual

A série usa Qt. O Raman Map ainda usa Tkinter. Os toolkits têm loops de eventos diferentes;
o modo Raman Map inicia outro processo do mesmo executável. A janela Qt é ocultada quando
a janela Tk está pronta. Ao sair do mapa, o Qt retorna com os dados da série em memória.
O usuário vê um workspace por vez.

Esta etapa não converte toda a interface antiga para Qt. Os rótulos do Raman Map permanecem em inglês.
Na versão 1.4.1, Data Quality usa controles Tk em português e um espectro integrado à própria tela.
`fazer_imagem` e todos os algoritmos de correção continuam intactos. A coleção apenas conecta o novo
painel aos callbacks existentes, preservando o estado independente de cada banda e as razões derivadas.
Os últimos caminhos do mapa ficam na pasta de dados do usuário, não na pasta do aplicativo instalado.
O EXE não tenta executar pip: formatos opcionais adicionais exigem um pacote que inclua suas dependências.

## Interface da série

Navegação fixa à esquerda; lista dos espectros; gráfico central; propriedades à direita.
O padrão é cascata 2D, espaçamento automático e alinhamento desativado.
A lista permite mostrar/ocultar, arrastar, mover e ordenar por temperatura.
Em telas abaixo de 1300 pixels, as propriedades são recolhidas e podem ser abertas em Opções.
O projeto avisa sobre alterações não salvas ao fechar ou substituir a série.

## Validação

`python -m unittest discover -s tests -v` executa testes numéricos e de fluxo da interface Qt:

- Integração e razão de áreas, incluindo valores inválidos e integridade dos dados.
- Espaçamento simples, alinhamento do professor, 3D e preservação das intensidades.
- Importação, temperatura em K, faixas e projetos com verificação de integridade.
- Lista/ordem/visibilidade, campos editáveis, layout compacto, salvamento e exportação PNG/PDF/SVG/CSV.

Os testes Qt usam uma janela real com plugin offscreen; não são imagens geradas.
O pipeline Windows executa os testes, abre ambos os workspaces empacotados,
instala o programa, verifica as entradas instaladas e executa a desinstalação.
A abertura automática não substitui conferir o uso e a apresentação no computador do laboratório.

## Compilar manualmente no Windows

```powershell
python -m pip install -r requirements-build.txt
python packaging/make_icon.py
python -m PyInstaller --noconfirm --clean packaging/imespec.spec
python packaging/smoke_frozen.py
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" packaging/windows.iss
```

O instalador usa escopo por usuário e inclui atalho e associação de `.imespec`.
A versão portátil mantém as bibliotecas compartilhadas junto do executável.
Metadados/licenças das distribuições científicas e do Qt acompanham o pacote.

Referências: [Qt for Python](https://doc.qt.io/qtforpython-6/),
[PyInstaller](https://pyinstaller.org/), [Inno Setup](https://jrsoftware.org/isinfo.php)
e [GitHub Actions](https://docs.github.com/en/actions).
