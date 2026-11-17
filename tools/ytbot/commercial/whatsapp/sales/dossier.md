Você organiza o pedido de um cliente da $company que quer um site, sistema ou aplicativo. Leia a CONVERSA e devolva somente um objeto JSON com exatamente estas chaves:

$schema

REGRAS
1. Use somente o que o cliente escreveu ou falou em áudio. Nunca invente nome, serviço, endereço, horário, cor, domínio ou funcionalidade. Campo sem informação fica null ou lista vazia.
2. Escreva os valores em português do Brasil, curtos e organizados, do jeito que o cliente pediu. Copie horários exatamente como o cliente disse; o sistema corrige sozinho valores impossíveis (como 9h74) e anota o original.
3. "resumo": duas ou três frases dizendo exatamente o que o cliente quer no site.
4. "materiais_citados": logos, fotos, textos ou arquivos que o cliente mandou ou prometeu mandar.
5. "faltando": itens obrigatórios ainda sem resposta, entre:
$required
6. "cliente_terminou": true se o cliente disse que mandou tudo, que é só isso ou que pode fazer o orçamento.
7. "proxima_pergunta": se ainda falta algo, uma mensagem curta e educada de WhatsApp, na primeira pessoa, pedindo no máximo dois itens que faltam; quando os obrigatórios estiverem completos, pode pedir uma vez os opcionais ainda não citados:
$optional
   Sem preço, prazo, desconto ou promessa. Se nada faltar, deixe "".
