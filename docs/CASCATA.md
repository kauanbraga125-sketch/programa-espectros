# Cascata: propósito, comportamento e limites

A cascata facilita comparar posição, largura e forma dos picos em uma série.
As curvas ficam separadas verticalmente. O deslocamento não é uma variação física medida da intensidade.

## Modos

**Sobrepor:** mostra `I_i(x)` no mesmo sistema de eixos. O alinhamento opcional fica desativado nesse modo.

**Cascata 2D:** mostra `I_exibida,i(x) = I_original,i(x) + c_i + i·delta`, com `i` começando em zero.
`delta` é o espaçamento; `c_i=0` no modo padrão. Os dados de entrada nunca são sobrescritos.

**Waterfall 3D:** X é Raman shift, Y é temperatura ou ordem da série e Z é intensidade.
Não se soma `i·delta` à intensidade: as curvas já estão separadas pelo eixo da série.
Temperaturas só são usadas como coordenadas quando todas são conhecidas e distintas.
Temperaturas repetidas ou ausentes usam ordem numerada para manter as curvas distinguíveis.
O Waterfall representa uma série espectral, não a topografia física da amostra.

## Espaçamento automático

Escolhe uma única constante suficientemente grande para separar cada curva da anterior,
considerando seus mínimos/máximos e uma folga de 12% da maior amplitude.
Isso mantém as diferenças de forma dentro de cada curva. É uma decisão de apresentação,
não um processamento de ruído, correção de resposta instrumental ou normalização.

## Alinhamento opcional

Em **Mais opções**, o usuário pode igualar as alturas em `x_ref` antes de empilhar.
O primeiro espectro visível é a referência. Para cada curva, usa-se a amostra medida
mais próxima de `x_ref`, conforme a rotina `distribuir` do professor:

`c_i = I_0(x_0 mais próximo) - I_i(x_i mais próximo)`.

Todos os espectros visíveis precisam conter `x_ref` dentro de seus intervalos medidos.
O alinhamento soma uma constante a cada curva, sem mudar os valores de Raman shift.
Ele não substitui a subtração de fundo para calcular áreas. Use as intensidades originais
para comparações numéricas de intensidades entre espectros.

## Importação e temperatura

O importador aceita TXT/CSV/TSV/ASC com duas colunas numéricas e cabeçalhos comuns.
A maior tabela numérica contígua é interpretada como o espectro.
Eixos não monotônicos, valores repetidos, NaN/Inf e tabelas com múltiplas colunas Y são rejeitados.
Arquivos de mapas devem ser abertos no módulo Raman Map.

Uma temperatura só é sugerida se o nome contiver explicitamente um número seguido de `K`.
Ela permanece editável. Números do laser, exposição ou ampliação não são temperaturas.
O nome `12_3K` sugere `12,3 K`, assim como `12.3K` e `12,3K`.
Confira a convenção da aquisição ao revisar a temperatura sugerida.
O nome sozinho não garante condições experimentais equivalentes: confira a aquisição antes
de interpretar diferenças de intensidade entre arquivos ou janelas.

Faixas sobrepostas pertencem ao mesmo grupo de visualização. O programa não interpola,
não une janelas em um espectro e não converte coordenadas espectrais em posições espaciais.

## Salvar e exportar

`.imespec`: JSON com esquema versionado, dados originais, ordem, visibilidade,
temperatura, cores, rótulos, opções e hashes SHA-256 de X/Y. O salvamento substitui o arquivo
de forma atômica. O projeto contém uma cópia dos dados e pode ser reaberto sem os TXT originais.

CSV: somente as curvas visíveis da região ativa, em formato longo, com X,
intensidade original, intensidade exibida e constante somada. As figuras podem ser
exportadas como PNG a 300 dpi ou PDF/SVG vetorial.

## Referências de interação

- [Origin: Stacked Lines by Y Offsets](https://docs.originlab.com/origin-help/stacklineyoffset-graph/)
- [Origin: controles de empilhamento](https://docs.originlab.com/origin-help/pd-dialog-stack-tab/)
- [Origin: Object Manager](https://docs.originlab.com/origin-help/object-manager/)
- [Origin: Waterfall 3D](https://docs.originlab.com/origin-help/3d-waterfall-graph/)

A organização foi adaptada ao IMESPEC; não se afirma reproduzir todos os algoritmos ou recursos do Origin.
