# Decisions

Short ADR-style log. Newest at the bottom. Format: context → decision → why → consequences.
Add an entry whenever you choose a tool, model or format, or deviate from the plan.

---

### D-001: Fully local, no paid APIs
- **Decision:** Every runtime component runs on the owner's machines. No API keys.
- **Why:** Cost, privacy, and learning self-hosted inference.
- **Consequences:** Lower ceiling on story and voice quality than frontier APIs. Models must fit in
  ~16 GB of Mac GPU memory, one at a time.

### D-002: 2D only, children's cut-out animation first
- **Decision:** v1 is rigged puppet (cut-out) 2D animation for children. No 3D. Anime tiers later.
- **Why:** Achievable locally, consistent by construction, and closest to proven preschool styles.

### D-003: Open-source apps animate, the LLM directs
- **Decision:** The LLM never generates frames. AI generates assets once. Synfig tweens rigged
  characters, and Kdenlive/MLT assembles the edit.
- **Why:** Frame-by-frame generation is slow, expensive and inconsistent. Rigs give consistency for free.

### D-004: Wrap apps via MCP servers, at the lowest integration level that works
- **Decision:** One Python MCP server per app. Level 1 (file formats, CLIs, APIs) by default. Level 2
  (in-app plugins) when needed. Level 3 (source changes) last.
- **Why:** Least brittle. Keeps our code separate from GPL apps. MCP is a core learning goal.

### D-005: No reverse engineering of proprietary tools
- **Decision:** Use open-source tools only (Synfig, OpenToonz, Krita, Kdenlive, ComfyUI...).
- **Why:** Commercial software licenses forbid reverse engineering and there is DMCA risk. Open-source
  equivalents exist.

### D-006: Synfig Studio as the animation engine
- **Decision:** Synfig for v1 (bones, skeleton deformation, switch layers, waypoint tweening, XML `.sif`
  format, `synfig` CLI renderer).
- **Why:** Its file format is plain XML that code can generate, and it renders headless from the CLI.
  Built for cut-out animation.
- **Alternatives considered:** OpenToonz (more powerful, harder to automate headless). A custom
  PixiJS/Remotion engine (maximum control, more to build). Revisit if Synfig blocks progress.

### D-007: Consistency from rigs, procedural faces, motion library
- **Decision:** Characters are generated once and rigged. Eyes, brows and mouths are code-generated
  vector shapes (mouth set = Rhubarb A–H, X). Motion comes from a parameterized library.
- **Why:** Exact lip-sync and expressions with no AI cost. Infinite reuse. No LoRA needed for v1.

### D-008: Film project folder is the source of truth
- **Decision:** Every stage reads and writes files in `films/<slug>/`. The state lives in `film.json`.
- **Why:** Human-in-the-loop fixes in real apps, crash-safe resume, easy debugging.

### D-009: Python 3.12 via uv for all environments
- **Decision:** Never use the system Python (3.15). Each package has its own uv-managed environment
  on Python 3.12.
- **Why:** PyTorch and most ML libraries don't support 3.15 yet.

### D-010: Models run natively; Docker only for services
- **Decision:** ML models run natively on macOS (Metal/MPS, MLX, Ollama). Docker is for Qdrant,
  Temporal and MinIO.
- **Why:** Docker on Mac has no GPU access.

### D-011: Two machines, introduced at Step 5
- **Decision:** The Mac is the AI node. The Windows laptop (4 GB RTX, 32 GB RAM) joins at Step 5 as
  the render and services node, through Temporal task queues by capability.
- **Why:** Keep early steps simple. Bring in distributed workers exactly when they solve a real need.

### D-012: Model license hygiene
- **Decision:** Check every model's license before download. Record it in MODELS.md. Prefer permissive
  licenses. Flag non-commercial ones clearly.
- **Why:** The owner may want to publish or monetize films later.

### D-013: Children's safety and style naming
- **Decision:** Age-appropriate content only, checked by `qa_mcp`. No real studio or living artist
  names in presets or prompts.
- **Why:** Ethics, legal risk, and platform policy (YouTube scrutinizes mass-produced kids' content).
