# Raman Map preservado

1. Abra a aquisição e confirme a geometria real. O número de espectros não estabelece X/Y sozinho.
2. Em Spectrum & Band, selecione uma faixa e gere o mapa.
3. Em Compare Maps, use Add band para gerar outro mapa da mesma aquisição.
4. Em Create ratio A/B, escolha numerador, denominador e critérios de validade.
5. Clique em um ponto para consultar os valores e o espectro na mesma posição dos mapas.
6. Use Show integration para revisar a reta de fundo local e a área integrada.
7. Exporte antes de sair do módulo.

## Revisar e corrigir em Data Quality

Abrir a aba **Data Quality** carrega diretamente o mapa de banda ativo. Se a seleção era uma razão,
a aba abre a banda usada no numerador. O seletor **Mapa** permite trocar de banda; as correções
continuam independentes. Sem mapas, o cabeçalho orienta gerar a primeira banda.

O mapa e o espectro ficam lado a lado em telas maiores e são empilhados quando o espaço diminui.
Um clique esquerdo consulta o ponto na própria tela; **Ampliar** abre Pixel Spectrum.
O painel mostra a área atual do mapa e a integral do espectro. Um reparo apenas do mapa é identificado.

**Raios cósmicos** atua nos espectros e recalcula o mapa. **Corrigir pixels do mapa** atua somente
no valor espacial. Os botões nativos chamam exatamente os callbacks anteriores de detecção,
aplicação, limpeza e restauração; limiares, mediana/médias e proteções não foram alterados.
O clique direito continua disponível para reparo manual e os candidatos automáticos exigem revisão
antes de aplicar. Os botões de aplicação são habilitados depois da detecção correspondente.

**Limpar marcações** descarta candidatos revisados. **Restaurar tudo** repõe espectros e mapa
ao estado inicial daquela banda. **Exportar análise** permanece acessível no rodapé do painel.

As bandas usam áreas assinadas após subtração do fundo linear local, em `a.u.·cm⁻¹`.
A razão divide áreas numéricas nas posições correspondentes; sua unidade é `1`.
Ela não divide cores das imagens nem é um quociente dos espectros completos.

O denominador deve ser estritamente maior que
`max(mínimo absoluto, porcentagem/100 × mediana dos valores positivos finitos de B)`.
O padrão relativo de 1% é uma heurística editável, não uma estimativa de ruído/SNR.
Não se substitui zero por epsilon. Pixels excluídos aparecem cinza e são exportados como ausentes,
com seu motivo. O numerador negativo é excluído por padrão, com opção de permitir valores assinados.

As razões são atualizadas após correção/restauração de uma banda de origem.
Um reparo apenas do mapa é identificado como map-only repair porque pode diferir da integral do espectro mostrado.
Remover uma banda informa as razões dependentes que também serão removidas.

O ZIP exportado contém `map.csv`, `metadata.json`, `map.png` e `README.txt`, com valores, validade,
bandas, parâmetros, unidades e hashes. Esse pacote conserva resultados, mas não reabre a sessão de edição.

Os eixos espaciais continuam em **pixels**. Uma barra em µm exige o passo real ou a calibração
da aquisição; cm⁻¹ e a quantidade de espectros não permitem deduzir essa escala física.

O núcleo `imespec_bib1.py` e o cálculo de razões foram conservados nesta migração.
A coleção conecta os mesmos algoritmos ao novo painel Data Quality. O launcher trata da navegação
e do funcionamento como aplicativo instalado.
