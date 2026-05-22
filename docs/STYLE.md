# Documentation Style Guide

This guide applies to all prose written for this charm. Read it before you write. Check against it before you commit.

---

## Voice

Write as a TA documenting a system, not a marketer selling it. Second person where useful. No congratulating the reader, no excitement about features.

---

## Don'ts and Do's

- **Don't** use emdashes as soft pauses.  
  *"This relation is optional — and easy to configure."*  
  **Write instead**: use a comma, a period, or restructure.  
  *"This relation is optional. Configure it with `juju integrate`."*

- **Don't** use: `delve`, `robust`, `seamless`, `leverage`, `comprehensive`, `powerful`, `elegant`, `intuitive`, `boast`, `navigate the complexities of`, `in the realm of`, `in today's fast-paced`, `pivotal`, `groundbreaking`, `vibrant`, `renowned`, `testament`.  
  *"This charm offers a robust, seamless integration with PostgreSQL."*  
  **Write instead**: say what it does.  
  *"This charm connects to PostgreSQL over the `pgsql` relation."*

- **Don't** open with hedging phrases.  
  *"It's worth noting that `log-level` defaults to `info`."*  
  **Write instead**: state the fact directly.  
  *"`log-level` defaults to `info`."*

- **Don't** use listicle padding to introduce content.  
  *"Here are the key things to keep in mind:", "Let's explore", "Without further ado".*  
  **Write instead**: cut the introducer and start the content.  
  *"Configure `executions-mode` before the first unit comes up."*

- **Don't** end paragraphs with motivational sentences.  
  *"Now you're ready to deploy n8n to your cluster."*  
  **Write instead**: stop when the instruction is complete.

- **Don't** use self-referential framing.  
  *"In this section, we will walk through configuring the PostgreSQL relation."*  
  **Write instead**: start the content.  
  *"Configure the PostgreSQL relation before the charm reaches `active`."*

- **Don't** open sections with rhetorical questions.  
  *"Why does the charm need a database relation?"*  
  **Write instead**: answer the question, put it first.  
  *"The charm requires a database relation to persist workflow state."*

- **Don't** write bullet lists where a sentence is clearer.  
  *"There are three steps: • Deploy the charm • Add the relation • Check juju status"*  
  **Write instead**: use a fenced code block for commands; prose for explanations.

- **Don't** attribute to unnamed sources or use vague quantifiers.  
  *"Some users have reported that `webhook-url` must be set before the first run."*  
  **Write instead**: state the constraint directly.  
  *"`webhook-url` must be set before the first execution or the unit blocks."*

- **Don't** use the "not just X, but Y" construction or rule-of-three padding.  
  *"Not just a workflow engine, but a scalable, flexible, and extensible automation platform."*  
  **Write instead**: one plain sentence.  
  *"n8n runs automation workflows and exposes a webhook endpoint."*

- **Don't** substitute simple verbs with copula replacements to sound varied.  
  *"This config key serves as the entry point for external traffic."*  
  **Write instead**: use `is`.  
  *"`external-hostname` is the hostname Traefik advertises to incoming traffic."*

- **Don't** inflate importance with words like `crucial`, `critical`, `important`, `essential` unless something will actually break.  
  *"It's important to set `executions-mode` correctly."*  
  **Write instead**: say what breaks.  
  *"If `executions-mode` is `queue`, a Redis relation is required or the unit blocks with `"missing redis relation"`."*

---

## Required Positive Patterns

**Name the file when introducing config keys, env vars, actions, or status strings.**  
Config keys, actions, and relations are all declared in `charmcraft.yaml` (this project uses a unified `charmcraft.yaml`, not a separate `actions.yaml` or `metadata.yaml`). Reference the file on first mention.

**Quote status strings verbatim in backticks.**  
The unit transitions to `"waiting for postgresql relation"` until `pgsql` is integrated.

**Show commands as fenced code blocks, not prose.**  
```bash
juju deploy n8n --channel edge
juju integrate n8n postgresql-k8s
juju config n8n log-level=debug
juju run n8n/0 get-encryption-key
```
Do not write "You can run `juju config` to change the log level if you want to."

**Lead with the operative information; put context after.**  
Wrong: "Because n8n stores workflow data in PostgreSQL, you need to integrate it before deploying."  
Right: "Integrate PostgreSQL before the first unit starts. n8n stores workflow state there and blocks without it."

**Use imperatives.**  
"Run `juju status`" not "You can run `juju status` to see the current state."

**Use Markdown headings (`##`, `###`). Never number sections.**  
`## Configure PostgreSQL` not `3. Configure PostgreSQL`.

**Code examples must run as-is on microk8s with juju 3.6.**  
No `<your-model>` placeholders. Use `n8n` as the app name (matches `name:` in `charmcraft.yaml`). Use `cos-lite` for the observability bundle. If a value genuinely varies, say so in prose after the block.
