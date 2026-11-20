# Handoff — Agente de vendas WhatsApp (Zaflas) + Central do app desktop

Gerado em 18/11/2026 07:05 (America/Cuiaba) ao sair do Claude Code para continuar no
Antigravity. Arquivo **não versionado**: não faça commit dele (apague quando não precisar mais).
Não contém número de telefone real nem a chave da API.

Leia primeiro `AGENTS.md` (regras do repositório) e o contrato do agente:
`docs/COMMERCIAL-WHATSAPP-SALES.md` (na branch `feat/whatsapp-sales-agent`).

---

## 1. Estado do Git

| PR | Branch | Último commit | CI | Situação |
| --- | --- | --- | --- | --- |
| [#77](https://github.com/AlexandreZanata/YoutubeBot/pull/77) agente de vendas | `feat/whatsapp-sales-agent` | `0e8ab19` | verde | aberto, mergeable |
| [#81](https://github.com/AlexandreZanata/YoutubeBot/pull/81) app desktop + Central | `feat/desktop-ui-refresh` | `f01c61b` | verde | aberto, mergeable |

- `main` está em `406321f` (outros PRs entraram depois: #78, #79, #80).
- Worktrees locais (cada branch tem a sua pasta):
  - `.claude/worktrees/whatsapp-sales` → `feat/whatsapp-sales-agent`
  - `.claude/worktrees/desktop-ui` → `feat/desktop-ui-refresh`
- A pasta principal (`main`) tem alterações **não commitadas de outra sessão** (pacing do X:
  `tools/ytbot/social/x/{publish,pacing}.py`, `docs/SOCIAL-*.md`, `tests/test_social_pacing.py`).
  Não mexer nelas.
- Os dois PRs editam parágrafos diferentes do `AGENTS.md` (vendas e desktop); o merge deve ser
  limpo. Sugestão de ordem: #77 e depois #81.

Commits do #77 (do mais novo para o mais antigo):

```text
0e8ab19 fix: reconnect after a suspend, neutral names, pause on any owner message
78c45d9 feat: free-first OpenCode model routing with paid fallback
63453bc feat: staff referrals, site close with Pix keys and owner end states
0056360 feat: category labels, phone contacts, Central snapshot and voice confidence
c1bf740 fix: save photo albums and type only into a reachable composer
d46a7a7 feat: client brief folder, voice transcription and quote collection
26f679b feat: hand conversations to the owner at the right moment
ff1568b fix: never promise the quote while offering it
01412f2 fix: read the 2026 chat list and speed up WhatsApp pacing
5d31ba8 feat: add the Zaflas WhatsApp sales agent
```

Commits do #81: `4825d40` redesign do app (trabalho da sessão "YoutubeBot Manager UI
refinement", commitado como estava), `4cefcc8` página Central, `bc122d6` merge de main,
`f01c61b` ajuste de colunas.

---

## 2. O que existe (resumo)

Código em `tools/ytbot/commercial/whatsapp/sales/` (reaproveita `sender.py` e `listener.py`
de `tools/ytbot/commercial/whatsapp/`, sem segundo caminho de envio):

| Arquivo | Papel |
| --- | --- |
| `sales_rules.toml` | **Fonte única** de textos, preços, chaves Pix, intenções, limites, horários, ritmo, modelos. O bot em execução recarrega o arquivo a cada ciclo (edição inválida é ignorada). |
| `context.md` | Instruções do modelo (pt-BR), regras 1–15 |
| `dossier.md` | Prompt de extração da ficha do cliente |
| `agent.py` | Máquina de estados, ingestão, respostas, aberturas, follow-up, indicação, fechamento, pausa quando o dono escreve |
| `decide.py` / `classifier.py` / `guard.py` | Decisão (classificador local + modelo + textos fixos), guarda contra preço/prazo/link/promessa fora das regras |
| `llm.py` | Roteador OpenCode Go: modelos **free** primeiro (catálogo ao vivo, preço 0), rotação, teste paralelo, pausas, fallback `deepseek-v4.1-flash` → `muse-spark-1.3-contributor` |
| `referral.py` | Extração de número e nomes (funcionário / responsável) |
| `dossier.py` | Pasta do cliente: `ficha.md`, `ficha.json`, `conversa.md`, `midia/` |
| `transcribe.py` | Áudio → texto local (faster-whisper large-v3-turbo, GPU, beam 5, confiança por palavra) |
| `central.py` | `central.json` para o app desktop (19 estados, intervenções, mensagens) |
| `store.py` | Leads, memória, não contatar (hash), rótulos `categoria-N`, vCard, import |
| `notify.py` | Notificação de handoff com nome, telefone, wa.me, motivo |
| `rehearsal.py` + `scenarios.json` | 33 conversas de ensaio offline (`sales rehearse`) |
| `commands.py` | CLI `commercial sales …` + loop com reconexão |

Fluxos implementados e testados (detalhes e diagramas no contrato):
- Abertura (4/2/8/8 s + 4 s por link), limite 10/dia, só em dia útil 08:30–17:30.
- Respostas 07:00–21:00, ritmo pelo tamanho da mensagem.
- Preços: **R$ 500 / R$ 250 / R$ 39,90 / R$ 45 / 15 dias são só do site institucional**;
  app/sistema sempre por orçamento (textos fixos + guarda).
- Fechamento do site → chaves Pix (`financeiro@zaflas.com.br`, chave aleatória) → estado
  "Venda fechada"; fechamento de sistema → "Quer comprar" (dono); desistência após interesse →
  "Desistiu" (dono, sem bloquear); recusa na abertura / "para de mandar" → não contatar.
- Funcionário → pede contato do responsável e o nome → número recebido vira lead de indicação
  com abertura própria ("{funcionário}, da empresa {empresa}, me passou o seu contato…").
- Coleta de dados após "sim" ao orçamento → ficha do cliente → 🔥 para o dono.
- Fotos (inclusive álbum) e áudios baixados para `clientes/.../midia/`; áudio transcrito e
  respondido; horário impossível aproximado (9h74 → 10h14) e anotado.
- Handoffs com prioridade (🔥 Atender agora / ⚠️ Precisa de você / 🛑 Verificar).
- Qualquer mensagem que o dono digitar no chat (depois da 1ª mensagem do bot) pausa o bot.

App desktop (`desktop/`, Rust + Slint): página **Central** (Ctrl+1) com "Precisa de você",
mensagens recentes, 19 estados e botões "Abrir conversa" (wa.me) e "Ficha do cliente".
Instalado em `~/.local/bin/ytbot-manager` a partir da branch do #81.

---

## 3. Estado privado (`.local/`, nunca vai para o Git)

| Caminho | Conteúdo |
| --- | --- |
| `.local/commercial/whatsapp/profile` | Perfil do Chrome com o WhatsApp Web logado (QR do dono) |
| `.local/commercial/whatsapp/{events,journal}.jsonl`, `rules.json` | Listener, diário de envios (cerca de envios incertos), regra de contatos |
| `.local/commercial/whatsapp/sales/leads.json` | Leads e estados |
| `.local/commercial/whatsapp/sales/conversations/*.jsonl` | Memória completa (ciclos antigos: `<lead>.cycleN.jsonl`) |
| `.local/commercial/whatsapp/sales/clientes/<empresa>-<lead>/` | Fichas e mídias dos clientes |
| `.local/commercial/whatsapp/sales/central.json` | Lido pelo app desktop |
| `.local/commercial/whatsapp/sales/contatos/{todos,novos-*}.vcf` | Contatos para importar no celular |
| `.local/commercial/whatsapp/sales/{handoff,decisions,llm-usage}.jsonl` | Handoffs, decisões (com o modelo que respondeu), custo |
| `.local/commercial/whatsapp/sales/models.json` | Cache do catálogo OpenCode |
| `.local/commercial/whatsapp/sales/llm.env` | `OPENCODE_GO_API_KEY` (chave de teste do dono, copiada do OpenTatu). **Nunca imprimir nem commitar.** |
| `.local/commercial/whatsapp/sales/debug/` | Prints de envios que falharam |

Leads hoje: só os de teste — `teste-1` (Felipe, número de teste do dono, estado "Indicou o
responsável") e `teste-2` (indicação recebida no teste, estado "Abordado"; o dono escreveu
"É o bot / Só ignora" nessa conversa, então o bot vai pausar sozinho quando abrir o chat).
**Ainda não há nenhum lead real importado.**

---

## 4. Como rodar

### O bot está rodando agora

Processo em segundo plano **desta sessão do Claude Code** (pid 695547), usando um lançador
temporário que roda o código da worktree `whatsapp-sales` contra o `.local/` da pasta principal.
Se a sessão do Claude fechar, o processo pode parar. Para conferir/parar:

```bash
pgrep -af "commercial sales run"
cat .local/commercial/whatsapp/sales/run.lock     # pid do run ativo (só um por vez)
kill <pid>                                         # parar com segurança entre ciclos
```

Antes de parar, confira que não há envio pela metade (deve imprimir `[]`):

```bash
python3 -c "import json;l={};[l.update({e['key']:e['state']}) for e in map(json.loads,open('.local/commercial/whatsapp/journal.jsonl'))];print([k for k,v in l.items() if v=='started'])"
```

### Depois do merge do #77 (recomendado)

Da pasta principal:

```bash
python3 -m tools.ytbot commercial status --network whatsapp       # navegador oculto logado?
python3 -m tools.ytbot commercial sales check --network whatsapp --ping
python3 -m tools.ytbot commercial sales models --network whatsapp # modelos free + teste paralelo
python3 -m tools.ytbot commercial sales run --network whatsapp --live --interval 15
python3 -m tools.ytbot commercial sales run --network whatsapp --live --prospect --limit 3
```

Para deixar rodando fora de qualquer editor: `nohup … > ~/zaflas-bot.log 2>&1 &` (ou um
serviço `systemd --user`). O loop reconecta sozinho se o computador suspender.

### Antes do merge

Rodar a partir da worktree apontando a raiz para a pasta principal (é o que o lançador faz):

```python
# salvar como /tmp/sales_run.py e rodar: python3 -I /tmp/sales_run.py commercial sales run --network whatsapp --live --interval 15
import sys
from pathlib import Path
sys.path.insert(0, "/home/iiii/PESSOAL-PROJETOS-ALEXANDRE/chatgpt-recorder/.claude/worktrees/whatsapp-sales")
from tools.ytbot import config
config.ROOT = Path("/home/iiii/PESSOAL-PROJETOS-ALEXANDRE/chatgpt-recorder")
from tools.ytbot.cli import main
sys.argv = ["ytbot", *sys.argv[1:]]
main()
```

### Comandos do dono

```bash
python3 -m tools.ytbot commercial sales import   --network whatsapp --csv ~/leads.csv   # name,phone,city,category,maps_url,website,note
python3 -m tools.ytbot commercial sales central  --network whatsapp                    # o que precisa de você
python3 -m tools.ytbot commercial sales handoffs --network whatsapp
python3 -m tools.ytbot commercial sales history  --network whatsapp --lead <id>
python3 -m tools.ytbot commercial sales resolve  --network whatsapp --lead <id> --state engaged|qualifying|closed
python3 -m tools.ytbot commercial sales block    --network whatsapp --lead <id>
python3 -m tools.ytbot commercial sales ficha    --network whatsapp --lead <id>
python3 -m tools.ytbot commercial sales contacts --network whatsapp                    # vCard de todos
python3 -m tools.ytbot commercial sales simulate --network whatsapp --text "Quanto custa?"
python3 -m tools.ytbot commercial sales rehearse --network whatsapp [--only "AC "]     # ensaio offline
python3 -m tools.ytbot commercial sales reset    --network whatsapp --lead <id> --yes  # só número de teste
```

App desktop depois do merge do #81: `bash desktop/scripts/install.sh --root "$PWD"` e reabrir.

### Verificação

```bash
npm ci && npm run verify                 # 460 testes Python + lint + pacote + publicação
cd desktop && cargo fmt --all --check && cargo test --workspace
```

Testes nunca enviam nada real: canal falso (`tests/sales_fixtures.py`), modelo falso, números
sintéticos `(65) 90000-00xx`.

---

## 5. Pendências e decisões em aberto

1. **Merge** dos PRs #77 e #81 (ambos verdes) e reinstalar o app desktop a partir da `main`.
2. **Primeira lista real**: montar o CSV revisado do Google Maps (sem raspagem) e importar;
   cada importação gera o vCard `contatos/novos-*.vcf` para importar no Google Contatos.
3. **Módulo de aquisição** (Receita Federal / busca manual no Maps): usar
   `SalesStore.import_rows(rows, now, source)` com `source` `receita-federal` ou
   `google-maps-manual`; numeração, validação, não contatar e vCard já ficam iguais.
4. **Cartão de contato** enviado no WhatsApp (sem número visível no texto): hoje vai para o
   dono ("salve o número e chame"); automatizar exige teste físico do DOM do cartão.
5. **Funcionário hostil** ("vai procurar o número certo"): hoje o bot pede o contato uma vez e
   fecha com gentileza se recusar. Decidir se quer pedir desculpas e encerrar direto.
6. **Privacidade dos modelos**: `iceman-contributor-free` e `muse-spark-1.3-contributor`
   treinam com os prompts (conversas dos clientes); `beam-free` não tem retenção zero. Para
   excluir: `llm.exclude` / `llm.fallback` no `sales_rules.toml`. O acordo de retenção zero do
   DeepSeek no OpenCode é renovado mensalmente (vale até 30/11/2026, rever).
7. **Testes físicos ainda não confirmados**: cartão de prévia dos links (o dono não confirmou),
   envio/recebimento de documento e vídeo, cartão de contato.
8. **`teste-2`**: indicação recebida no teste (o dono avisou a pessoa). Opcional bloquear:
   `commercial sales block --lead <id do teste-2>`.
9. **Texto de espera do "unknown"**: "Certo! Vou verificar direitinho e já te respondo." serve
   para pergunta, mas soa estranho para um comentário solto (ex.: 18/11 07:11 Felipe mandou
   "estudaram meu ouvido" e recebeu esse texto; a conversa foi para o dono). Avaliar um texto
   para mensagens que não são perguntas.
10. O lançador temporário e os logs estão no scratchpad desta sessão
   (`/tmp/claude-1000/.../scratchpad/`) e somem; use os comandos acima.

---

## 6. Regras que não podem ser quebradas

- `--live` obrigatório para enviar; sem ele é só plano (dry-run).
- Nunca reenviar um envio `started`/`unconfirmed`/`error` do `journal.jsonl` (cerca); o loop
  para e notifica.
- Recusa na abertura / opt-out = não contatar permanente (hash em `do-not-contact.json`).
- Nunca inventar preço, prazo, desconto, chave Pix ou promessa fora do `sales_rules.toml`.
- Honestidade: perguntado se é robô, o bot diz que é assistente automático do Alexandre.
- Nada de evasão de detecção do WhatsApp, troca de identidade ou disparo em massa.
- `.local/`, a chave da API e números reais nunca vão para o Git; textos pt-BR, código e docs
  em inglês (ver `AGENTS.md`).
