# Análise de picos e sobretons

## Para que serve

Estimar centros, larguras e áreas das bandas Raman por um modelo explícito,
para comparar a série térmica e os sobretons. O maior ponto de um espectro
não é, em geral, o centro de um perfil ajustado. A análise é acessível por
**Análise > Ajustar picos e sobretons** (Ctrl+3) e pelo botão **Analisar picos**.

1. Abra os TXT/CSV da série.
2. Escolha a região, o perfil e o fundo; use o preset como ponto de partida.
3. Clique em Ajustar série.
4. Selecione uma linha para ver dados, ajuste, componentes, fundo e resíduos.
5. Revise as sinalizações e exporte JSON, parâmetros CSV e comparações CSV.

São analisados todos os arquivos abertos que cobrem a janela inteira, ou
somente os visíveis se essa opção estiver marcada. O programa não extrapola
uma janela ausente. “Volta”, temperatura não informada e correspondências
ambíguas são preservadas e não são misturadas silenciosamente.

## Modelos

Lorentziana, Gaussiana e Pseudo-Voigt têm área A, centro c e FWHM w. A
Pseudo-Voigt é a mistura de uma Gaussiana e de uma Lorentziana com a mesma
área e FWHM; sua fração Lorentziana varia entre 0 e 1.

- Lorentziana: caudas mais longas; um ponto de partida descrito na literatura de CLC confinadas.
- Gaussiana: caudas mais curtas; pode representar outros mecanismos de alargamento.
- Pseudo-Voigt: permite uma mistura; tem mais parâmetros e pode ficar pouco identificável em sinais fracos.

O perfil é uma hipótese do ajuste, não um identificador automático do
material ou do mecanismo de alargamento. Compare resíduos e sensibilidade
a outro perfil/fundo antes de escolher. Não selecione um modelo apenas
porque ele produz um centro próximo do valor esperado.

## Presets e fundo

O preset CLC usa duas componentes para representar um ombro e a banda
principal; uma componente também pode ser escolhida. Isso é uma descrição
fenomenológica, não prova de duas populações ou modos. A tabela e as
comparações usam a componente principal; ambas ficam no JSON e no gráfico.

As janelas iniciais são C: 1780-1940; 2C: 3570-3830; 3C: 5460-5590; e candidato
4C: 7228-7325 cm^-1. Cada centro tem limites de busca e larguras permitidas,
visíveis na configuração exportada. Não são limites universais para outras
amostras. O preset Personalizado permite outra janela e uma ou duas componentes.

O fundo constante, linear ou quadrático é ajustado simultaneamente ao
perfil, sem sobrescrever o espectro. Ao mudar o fundo, a área e o centro
podem mudar. Verifique que as bordas da janela realmente restringem o fundo.

## Resíduos, sinais estreitos e limitações

A opção robusta usa soft_l1 para reduzir a influência de resíduos extremos.
Todos os pontos continuam no ajuste e no gráfico; nenhum dado é apagado,
suavizado ou reparado. Isso não identifica automaticamente raios cósmicos.
Apenas a estimativa inicial usa uma mediana de cinco pontos.

Há sinalização para não convergência, baixa altura/ruído estimado, centro ou
largura no limite, jacobiano deficiente, centro pouco determinado, resíduos
acima do ruído e reamostragem insuficiente. Esses critérios são heurísticos
explícitos: convergência e ausência de sinalizações não confirmam uma
atribuição física. O candidato 4C não é liberado automaticamente para as
comparações físicas.

## Erros estatísticos

Com zero reamostragens, usa-se uma covariância local aproximada. Em Mais
opções, 100 reamostragens ou mais permitem estimar o desvio padrão por
bootstrap de resíduos independentes, com semente reprodutível.

São erros condicionais ao modelo, janela e hipótese de ruído. Não incluem
calibração, resolução/linha instrumental, incerteza de temperatura,
correlações entre resíduos, mudança de perfil ou de fundo. Maior precisão
estatística que a malha de X não certifica essa mesma exatidão experimental.
O JSON identifica o método e quantas reamostragens convergiram.

## Sobretons

C é a ordem 1; 2C, 3C e 4C são primeiro, segundo e terceiro sobretons.
A comparação segue a definição de Lechner et al. (2025):

    delta_rel,n (%) = 100 * [nu1 - (nu_n - nu_(n-1))] / nu1

Para n=2, nu_(n-1)=nu1. Para n=3 ou 4, é necessária a ordem anterior.
A referência harmônica tem delta=0. O erro estatístico é propagado supondo
ajustes independentes, sem erros comuns de calibração. Esse delta **não é**
o parâmetro de anarmonicidade chi de um potencial ajustado.

As janelas são associadas por nomes compatíveis, temperatura e indicação
“volta”. O nome não certifica mesma posição da amostra, condições idênticas
ou que as bandas pertençam à mesma cadeia. Em bandas de ensemble, a
comparação não deve ser atribuída a uma cadeia única sem evidência adicional.

## Áreas e razões

A área do modelo é a integral do perfil da componente principal sobre todo
o domínio, em a.u.*cm^-1. Também se exporta a área restrita à janela. A
primeira pode depender mais das caudas e do perfil escolhido. As comparações
usam a área da componente principal, não somam automaticamente o ombro.

Os divisores de área, inicialmente 1, permitem parâmetros informados pelo
usuário, por exemplo tempo de aquisição verificado. A razão continua sendo
dos sinais exportados; a resposta espectral e os fatores não são certificados
pelo programa. A incerteza dos fatores não é incluída automaticamente.
Não interpretar esse quociente como concentração ou intensidade intrínseca
sem validar condições de aquisição, atribuições e resposta instrumental.

## Reproduzir sem interface

    python -m imespec_app.peak_cli pasta_de_txt --output resultados/ajustes --bootstrap 100

Opções: --model lorentzian|gaussian|pseudo_voigt, --baseline-degree 0|1|2,
--band all|C|2C|3C|4C e --ordinary-least-squares.

O JSON contém vetores medidos na janela, modelo, resíduos, componentes,
configuração, impressões digitais dos dados, sinalizações e comparações.
CSV de parâmetros e CSV de sobretons facilitam a revisão e exportação.
Os originais e o projeto da série não são alterados; o relatório de ajuste
é um arquivo separado.

## Fontes

- Lechner et al., Nature Communications 16, 4360 (2025): https://doi.org/10.1038/s41467-025-59555-y
- SciPy least_squares: https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.least_squares.html
- SciPy curve_fit (limites da covariância): https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.curve_fit.html
- Definições normalizadas de perfis: https://lmfit.github.io/lmfit-py/builtin_models.html
