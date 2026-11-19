# Playbook e Roadmap de Pesquisa de Leads — Google Maps (Zaflas Inova Simples)

> **Leia este documento por completo antes de iniciar qualquer rodada de pesquisa.**
> Ele define a ordem de prioridade dos próximos ciclos, o alinhamento com os 4 sites de exemplo enviados na abordagem e os critérios objetivos para selecionar bons comércios.

---

## 1. Regras obrigatórias antes de começar

Antes de rodar qualquer comando, o agente de pesquisa deve:

1. **Ler os arquivos de referência do projeto:**
   - Contrato técnico e limites do módulo: `docs/COMMERCIAL-MAPS-RESEARCH.md`
   - Regras de busca, exclusões e pontuação: `tools/ytbot/commercial/maps/maps_rules.toml`
   - Mensagem de abertura e os 4 links de exemplo: `tools/ytbot/commercial/whatsapp/sales/sales_rules.toml`
2. **Checar a sessão do Google Maps:**
   ```bash
   python3 -m tools.ytbot commercial maps status
   ```
   Se não estiver conectado (`logged-in`), parar e avisar o dono para autenticar manualmente (`commercial maps login`). Nunca automatizar login, senha, 2FA ou CAPTCHA.
3. **Respeitar rigorosamente os limites operacionais:**
   - **Somente leitura** no Google Maps, 1 aba, ritmo humano, teto diário de `limits.daily_businesses` (120 empresas/dia).
   - **Parar imediatamente** em caso de CAPTCHA, "tráfego incomum", desafio de login ou layout desconhecido (código de saída `2`), registrar e avisar o dono. Nunca contornar ou tentar em loop.
   - **Nunca importar leads nem enviar mensagens:** o papel do agente de pesquisa termina na entrega do `candidatos.csv`, `ajuste-maps.csv`, `report.md` e da lista curada para aprovação manual do dono.
   - **Nunca repetir empresas já contatadas ou bloqueadas:** o `export` já filtra `commercial sales leads` e `do-not-contact` (o lote inicial de 10 clínicas odontológicas em Sinop já foi enviado).
   - **Nunca expor nem commitar** dados privados de `.local/` (telefones, perfis, cookies, runs).

---

## 2. Alinhamento com os 4 sites de exemplo da abertura

Na abordagem inicial (`sales_rules.toml`), todo lead recebe 4 links reais da Zaflas Inova Simples. Os ciclos de pesquisa priorizam ramos em que o dono **abre um dos 4 exemplos e se identifica imediatamente**, aumentando resposta e conversão — tanto para o **site institucional (R$ 500, entrada R$ 250, servidor R$ 39,90/mês no Pix/boleto ou R$ 45 no cartão)** quanto para **sistemas e aplicativos sob medida (orçamento específico)**.

| Site de exemplo | O que demonstra | Ramos com maior aderência | Oferta principal |
| --- | --- | --- | --- |
| `https://zaflas.com.br` | SaaS de gestão agrícola (produção, operação, finanças, rastreabilidade) | Agro, consultoria agronômica, revendas, peças/oficinas de máquinas, irrigação, transportadoras agrícolas | Site + formulário de orçamento; gancho forte para sistemas sob medida (frota, pedidos, visitas) |
| `https://sorrifit.com` | App/site de treino de musculação, fitness, saúde e rotina | Academias, pilates, CrossFit/funcional, fisioterapia, nutrição, clínicas de estética | Site institucional moderno + agendamento / acompanhamento |
| `https://abastevo.com.br` | Plataforma/app de preços de combustíveis, motoristas e frotas | Oficinas mecânicas, auto centers, auto elétricas, funilaria, estética automotiva, autopeças, guinchos, locadoras | Site institucional + agendamento de serviços / sistemas de frota ou OS |
| `https://musicalizese.com.br` | Site institucional acolhedor de educação musical, arte, cultura e musicoterapia | Escolas de música, idiomas, reforço escolar, escolas infantis, autoescolas, psicólogos, fonoaudiologia, clínicas multidisciplinares | Site institucional claro e humanizado + captação de matrícula/consultas no WhatsApp |

---

## 3. Roadmap priorizado — Próximos 4 ciclos imediatos (Onda 1: Sinop - MT)

A cadência de disparo do agente de vendas é de **30 aberturas frias por dia útil** (decisão do dono em 2026-11-19). Portanto, cada ciclo de pesquisa deve entregar **20 a 30 comércios excelentes** (curados e ordenados por prioridade), suficientes para 1 a 2 dias úteis de prospecção por nicho.

### Resumo da ordem de execução

| Ordem | Ciclo | Grupo (`--group`) | Site-âncora | Meta curada |
| :---: | --- | --- | --- | --- |
| **1º** | **Agro** | `agro` | `zaflas.com.br` | 10–20 empresas |
| **2º** | **Fitness & Estética** | `saude` (priorizando fitness/estética) | `sorrifit.com` | 10–20 empresas |
| **3º** | **Automotivo** | `automotivo` | `abastevo.com.br` | 10–20 empresas |
| **4º** | **Educação & Terapias** | `educacao` (+ `psicólogo`) | `musicalizese.com.br` | 10–20 empresas |

---

### Ciclo 1 — Agro (Prioridade 1)

- **Justificativa:** maior poder aquisitivo em Sinop - MT, menor saturação de abordagens de sites e maior potencial de evoluir do site institucional para um sistema sob medida graças ao `zaflas.com.br`.
- **Buscas já configuradas em `maps_rules.toml` (`group = "agro"`):**
  - `revenda de insumos agrícolas`
  - `peças para máquinas agrícolas`
  - `oficina de máquinas agrícolas`
  - `consultoria agronômica`
  - `georreferenciamento`
  - `irrigação`
  - `transportadora`
  - `veterinário de grandes animais`
- **Subnichos extras (sugerir ao dono adicionar em `maps_rules.toml` se precisar ampliar o volume):** `topografia`, `casa agropecuária`, `armazém agrícola`, `energia solar`.
- **Comandos do ciclo:**
  ```bash
  python3 -m tools.ytbot commercial maps research --city "Sinop" --state MT --group agro --limit 60
  python3 -m tools.ytbot commercial maps verify --run sinop
  python3 -m tools.ytbot commercial maps export --run sinop
  ```

---

### Ciclo 2 — Fitness & Estética (Prioridade 2)

- **Justificativa:** altíssima afinidade visual com `sorrifit.com` (que inclusive é o primeiro link enviado na abertura) e grande quantidade de negócios bem avaliados que usam apenas Instagram (`social-only`).
- **Foco obrigatório dentro do grupo `saude`:**
  - `academia`
  - `studio de pilates`
  - `fisioterapia`
  - `nutricionista`
  - `clínica de estética`
- **Atenção operacional antes de rodar este ciclo:** em `tools/ytbot/commercial/maps/maps_rules.toml`, o grupo `saude` atualmente lista `dentista` e `clínica odontológica` no topo. Como o lote inicial de odontologia já foi disparado, **não desperdice o `--limit` repetindo dentistas**: antes de executar o Ciclo 2, verificar se a ordem das buscas em `[[searches]]` do grupo `saude` já prioriza `academia`, `studio de pilates`, `clínica de estética`, `fisioterapia` e `nutricionista` (caso contrário, alinhar com o dono para reordenar `maps_rules.toml` antes da busca).
- **Subnichos extras recomendados:** `crossfit`, `treinamento funcional`, `quiropraxia`.
- **Comandos do ciclo:**
  ```bash
  python3 -m tools.ytbot commercial maps research --city "Sinop" --state MT --group saude --limit 60
  python3 -m tools.ytbot commercial maps verify --run sinop
  python3 -m tools.ytbot commercial maps export --run sinop
  ```

---

### Ciclo 3 — Automotivo (Prioridade 3)

- **Justificativa:** grande volume de oficinas, auto centers e serviços automotivos bem avaliados no Maps sem site próprio, com conexão direta ao `abastevo.com.br`.
- **Buscas já configuradas em `maps_rules.toml` (`group = "automotivo"`):**
  - `oficina mecânica`
  - `auto center`
  - `funilaria`
  - `autopeças`
  - `loja de pneus`
  - `auto elétrica`
- **Subnichos extras de alto ticket recomendados:** `estética automotiva` (polimento/vitrificação/detalhamento), `guincho 24h`, `locadora de veículos`.
- **Comandos do ciclo:**
  ```bash
  python3 -m tools.ytbot commercial maps research --city "Sinop" --state MT --group automotivo --limit 60
  python3 -m tools.ytbot commercial maps verify --run sinop
  python3 -m tools.ytbot commercial maps export --run sinop
  ```

---

### Ciclo 4 — Educação & Terapias (Prioridade 4)

- **Justificativa:** público que valoriza credibilidade institucional na busca do Google (pais, alunos e pacientes pesquisam antes de entrar em contato) e entende rapidamente o valor de um site institucional ao ver o `musicalizese.com.br`.
- **Buscas já configuradas em `maps_rules.toml` (`group = "educacao"`):**
  - `escola de idiomas`
  - `autoescola`
  - `escola de música`
  - `reforço escolar`
- **Complemento em `saude`:** incluir `psicólogo` na curadoria deste ciclo (e, se o dono autorizar ampliar `maps_rules.toml`, adicionar `fonoaudiologia`, `clínica multidisciplinar`, `escola infantil` / `berçário` e `escola de dança`).
- **Comandos do ciclo:**
  ```bash
  python3 -m tools.ytbot commercial maps research --city "Sinop" --state MT --group educacao --limit 50
  python3 -m tools.ytbot commercial maps verify --run sinop
  python3 -m tools.ytbot commercial maps export --run sinop
  ```

---

### Onda 2 — Expansão após os 4 ciclos iniciais

Depois de concluir e disparar os 4 ciclos em Sinop (40 a 80 leads), usar os resultados reais de resposta e pedido de orçamento para:

1. **Repetir os 2 nichos campeões** em **Sorriso - MT** e **Lucas do Rio Verde - MT**.
2. Em **Sinop - MT**, avançar para os grupos secundários de alto ticket:
   - `casa`: móveis planejados, energia solar, marmoraria, vidraçaria, ar-condicionado.
   - `servicos`: arquitetura, engenharia, imobiliária, contabilidade, corretora de seguros.

---

## 4. Guia de seleção: como escolher bons comércios na curadoria

O `export` já remove fechados, sem telefone, exclusões configuradas, quem já tem site próprio funcionando e Tier C (< 50 pontos). Porém, como o limite de envio é de **30 leads/dia**, o agente de pesquisa deve ranquear e filtrar o `candidatos.csv` usando estes critérios antes de apresentar a lista final ao dono:

### A. Sinais verdes — Prioridade máxima (colocar no topo da lista)

1. **Classe de site `social-only` (Instagram, Linktree, bio-link ou `wa.me` no campo de site):**
   - Melhor sinal possível: a empresa já investe tempo e atenção em presença digital, mas depende 100% de rede social e perde quem busca no Google.
2. **Tier A (70+ pontos) e melhores Tier B (60–69 pontos) com perfil vivo:**
   - Nota **4.5 ou maior**, **25+ avaliações** e **avaliação recente nos últimos 90 dias**. Indica negócio ativo, com fluxo real de clientes e caixa para investir.
3. **Telefone celular (9 dígitos começando com `9`):**
   - Alta probabilidade de WhatsApp ativo direto com o dono ou recepção próxima ao decisor.
4. **Fotos reais e horário preenchido no perfil do Maps:**
   - Confirma estrutura física estabelecida e cuidado com a imagem da marca.
5. **Marca própria clara e serviço de ticket médio/alto:**
   - Empresas cujo valor de 1 ou 2 clientes novos vindos do Google já paga com folga o site institucional (ex.: revisão de máquina agrícola, matrícula de pilates/idiomas, estética automotiva, procedimento estético).

### B. Sinais amarelos — Segunda prioridade (usar para completar lote, com aviso na nota)

1. **Poucas avaliações (5 a 15), porém todas muito recentes:**
   - Pode ser negócio recém-inaugurado (momento ótimo para montar o primeiro site), desde que tenha fotos reais e telefone celular válido.
2. **Profissional autônomo / solo (ex.: psicólogo ou nutricionista individual):**
   - Decisor direto (sem secretária filtrando), ótimo para fechar site institucional rápido, mas menor potencial de virar projeto de sistema sob medida.
3. **Telefone fixo:**
   - Nem todo fixo está no WhatsApp Business; manter abaixo dos celulares na ordem de prioridade.

### C. Sinais vermelhos — Cortar ou sinalizar para remoção antes da aprovação

1. **Franquias e redes nacionais/regionais disfarçadas:**
   - Mesmo que não estejam ainda em `[exclusions].name_terms`, unidades franqueadas quase nunca podem contratar site próprio fora do padrão da matriz (ex.: grandes redes de academias, estética, idiomas, autopeças, escolas). Se detectar uma nova rede, anotar para adicionar em `[exclusions]`.
2. **Negócio aparentemente inativo ou excessivamente informal:**
   - 0 a 3 avaliações antigas (mais de 1 ano), sem fotos reais, sem horário de funcionamento ou com nome genérico demais sem identidade comercial.
3. **Nota baixa (abaixo de 4.0) com reclamações recentes de atendimento:**
   - Alta chance de dono sobrecarregado, difícil de fechar e difícil de entregar materiais (logo/fotos) para o projeto.
4. **Site próprio já existente encontrado na confirmação (`site-not-on-maps`):**
   - Vai automaticamente para `ajuste-maps.csv`; nunca misturar no lote de "vocês não têm site".
5. **Concorrentes diretos ou empresas de tecnologia/marketing:**
   - Agências de marketing, produtoras digitais, consultorias de TI ou gráficas que já vendem criação de sites.
6. **Cidade errada no endereço:**
   - O feed do Maps às vezes retorna empresas de cidades vizinhas (ex.: Sorriso em busca de Sinop). Conferir se o endereço pertence à cidade do ciclo.

---

## 5. Checklist de execução e formato de entrega do agente de pesquisa

Ao concluir cada ciclo, o agente deve entregar ao dono um resumo curto e objetivo contendo:

1. **Identificação do ciclo:** cidade, data, grupo pesquisado, comando usado e caminho da pasta em `.local/commercial/maps/runs/<cidade>/<data>/`.
2. **Funil numérico da rodada:**
   - Empresas lidas no Maps
   - Confirmadas em `verify` (`no-site`, `site-not-on-maps`, `weak-site`, `has-site`)
   - Excluídas (fechadas, outra cidade, franquia/exclusão, já contatadas, Tier C)
   - Total final em `candidatos.csv` e `ajuste-maps.csv`
3. **Top 20 a 30 recomendados para o próximo lote de disparo:**
   - Lista ordenada do melhor para o menor potencial, mostrando: nome, categoria, tier/score, classe do site (`social-only`/`none`/`marketplace`), nota/avaliações, tipo de telefone (celular/fixo) e **por que entrou** (ex.: `social-only + 4.9 (87) + agro B2B`).
4. **Alertas de curadoria:**
   - Eventuais candidatos duvidosos (sinais amarelos/vermelhos) que o dono deve conferir antes de importar.
   - Novas franquias ou diretórios encontrados no Google para sugerir inclusão em `exclusions` ou `confirmation.ignore_domains` no `maps_rules.toml`.
5. **Próximo passo (somente após aprovação do dono):**
   ```bash
   python3 -m tools.ytbot commercial sales import --network whatsapp \
     --csv .local/commercial/maps/runs/<cidade>/<data>/candidatos.csv \
     --source google-maps-manual
   ```

---

## 6. Retroalimentação entre ciclos (métricas para escalar na Onda 2)

Após o disparo de cada ciclo (20 a 30 leads), registrar para comparar nichos:

- **Taxa de resposta útil** (desconsiderando auto-respostas de WhatsApp Business)
- **Qual dos 4 exemplos gerou comentário/interesse**
- **Pedidos de orçamento:** site institucional vs. sistema/aplicativo sob medida
- **Recusas / opt-outs** (se um subnicho gerar recusa recorrente, despriorizar nas próximas cidades)
