# Open Agent

Open Agent is a local chat and coding assistant for an OpenAI-compatible model server. Start a conversation without selecting a project, or open the coding workspace to plan a change, approve actions, and review test results. SQLite stores conversations, tasks, approvals, preferences, and tool metadata in the local `data/` directory.

## Start on Windows

1. Install Python 3.12, Node.js 24, Git, and a local model server. If you use Ollama, start it and check that your model appears in `ollama list`.
2. In PowerShell, from this folder, run:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   npm --prefix frontend ci
   npm --prefix frontend run build
   .\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8765
   ```

3. Open `http://127.0.0.1:8765` in your browser. Leave the terminal open while using the app. Stop it with Ctrl+C.
4. In **Settings**, check the connection and model name. The app prefers an installed `ornith-1.5:9b`, then discovers an available GPT-OSS model from `http://127.0.0.1:11434/v1` by default. Another local OpenAI-compatible endpoint can be configured there. The model must support chat completions and follow the agent's JSON instructions; a model is never downloaded automatically.
5. Start in **Chat** for a regular conversation and use **Workspace** for project work. Conversations are saved and can be reopened.
6. In **Workspace**, enter an existing project directory and your task. Open **Approvals** to review each proposed edit, command, or download. Give the agent clarifications from the task view when it is paused or blocked.

For development, run `npm --prefix frontend run dev` in a separate terminal; the Vite server proxies `/api` to the backend. Use the production URL above for ordinary use. Run tests with `python -m pytest -q`.

## Build a frontend

In **Workspace**, select an empty project folder and try “Build a responsive editorial website for a weekend listening festival. Include the programme and expandable session descriptions. Use forest green and animate the artwork with Anime.js.”

The built-in `design_page` tool takes a short brief with a brand, headline, introduction, section name, palette and entries. Choose a programme with expandable rows or a catalogue with searchable cards. It proposes the exact HTML for approval and creates a new file. It bundles the animation library into the page, so the result opens offline. Native disclosures support keyboard input, and the animation respects reduced-motion preferences. Existing React or other framework projects use the regular component editing tools.

Ask in **Chat** for a single HTML file with inline CSS and JavaScript. When the reply contains a standalone document, OpenAgent opens its preview beside the code on desktop and above the conversation on smaller screens. You can switch viewport sizes, interact with the page, and download the source. The preview renders locally and blocks external requests. If a reply ends mid-document, the preview labels it as incomplete.

Open [the Listening Room example](examples/listening-room/index.html) locally, or serve it with `python -m http.server 8090 --bind 127.0.0.1 --directory examples/listening-room`. In **Tools → Browser inspector**, open `http://127.0.0.1:8090/index.html` and choose Phone or Desktop. To test with the agent, give it the URL and ask it to verify both widths and open the first session. The `browser_layout` check measures horizontal overflow on the rendered page and reports example elements to inspect when it fails. It works on existing sites too.

For a standalone HTML file, the agent can use `browser_project` after approval to render the selected file directly, without a server. The preview checks the approved file hash and serves only those bytes. Use the URL preview for multi-file apps.

The bundled Anime.js UMD build comes from npm package `animejs@4.2.2`. Its [MIT license](backend/design_assets/vendor/anime-LICENSE.md) is included in each generated page.

## Engineering workflow

Select a project in **Workspace**. Ask the agent to locate the code, reproduce the failure, propose a targeted edit, and rerun the relevant check. It can discover pytest, unittest, and existing npm test, lint, typecheck, or build scripts in a directory within the project. Named checks show the approved executable and arguments, including npm pre/post scripts when present. Results contain an exit code, elapsed time, and captured output. Python checks use the interpreter running Open Agent. Execute checks only in projects you trust because test and build scripts run project code.

Open **Tools → Browser inspector** to inspect a local development page such as `http://127.0.0.1:3000` or a public HTTPS page. The preview includes a screenshot, an accessibility outline, and page errors and failed requests. Click or scroll the preview, activate an exact named control, or fill a labelled field with test data.

Install the browser once with `python -m playwright install chromium --only-shell` using the app's Python environment. On Linux, install the Chromium system dependencies with `python -m playwright install-deps chromium`. To use installed Google Chrome or Microsoft Edge instead, set `OPEN_AGENT_BROWSER_CHANNEL` to `chrome` or `msedge` before launching Open Agent.

To verify a behavior from a coding task, include the URL and expected result in your request. Opening the URL and clicking or filling controls each require approval. The agent can cite a deterministic assertion for an exact accessible name and role in its task review. Select the task's browser session in **Browser inspector** to inspect its screenshot and diagnostics. Sessions expire after 20 minutes without activity and close when Open Agent stops.

In **Chat**, open the attachment menu and choose a browser preview to discuss the page with the local model. The selected accessibility outline and recent errors are saved with that message. Chat attachments use a captured snapshot.

The integrated browser is designed for development previews and public reference pages. It uses fresh Chromium contexts, GET/HEAD requests on the selected origin, and a fixed, validated address for each session. Enter the final URL for redirects. Cross-origin assets, login sessions, form submissions, downloads, and WebSockets are outside this preview mode. Use explicit loopback URLs for local apps. Open Agent and its model endpoint are excluded on their default ports.

## How it works and current limits

- The agent plans, gathers evidence, proposes one action at a time, reviews each requirement against recorded results, and separately checks its draft final response. An unsuccessful review can trigger a focused repair, up to the configured retry limit. A model's review is not a guarantee; inspect the evidence and output yourself. Model errors and unavailable tests are reported as blockers.
- File reads support inclusive line ranges. A targeted edit replaces one exact match after approval and rejects changes to a file made since the proposal. Git status and diff use fixed commands with approval. Approved terminal commands run with your user account's permissions and can affect paths outside the project. Pausing or cancelling cannot stop a command already executing.
- Restarted tasks are paused. Actions interrupted during execution are marked as uncertain and must be inspected and acknowledged before resuming; they are not replayed automatically.
- GitHub imports support repository URLs and file URLs in `github.com/owner/repo/blob/branch/path` form. Repository clones require Git. Files are saved in `data/skills`, disabled by default, and never installed or executed automatically. Inspect and enable a root `SKILL.md` to make its content available as untrusted reference material to the agent. Removing an imported tool requires approval. Branch names containing `/` are not supported in file URLs.
- Long-term memory can be added and edited in the Memory screen. Clear preferences stated in your own task messages (such as "I prefer Python") are also saved automatically; the Memory screen shows their source and lets you disable or delete them. Repository text and tool output are never automatically saved as memories. Retrieval prioritizes keyword matches and then recent enabled memories, so it may miss relevant context. Cloud synchronization is not implemented.
- Context and response sizes are limited to suit a laptop. The adapter requests JSON output and low reasoning effort when the runtime supports them, with a larger response budget to leave room for a final action. Large code changes may need to be broken into smaller tasks. The 16 GB RAM configuration may be slow or run out of memory depending on other applications, the model's context size, and GPU offloading.
- The app is intended for one trusted user on one computer. Keep it bound to `127.0.0.1`; it has no account system or remote-access authentication. Do not expose it to the network.

## Development and contributions

See [CONTRIBUTING.md](CONTRIBUTING.md) for the branch workflow and checks. Set `OPEN_AGENT_TEST_BROWSER=1` to run the local browser fixture alongside the regular test suite. The optional `python tests/live_smoke.py` run exercises an isolated task against your configured local model. Its test harness approves only the expected fixture write.

Open Agent is distributed under the [MIT license](LICENSE).

### Appearance and task evidence

Use **Settings → Appearance** to follow the system theme or save a light or dark preference in the current browser. The integrated browser keeps the previewed site's own colours.

In **Workspace**, select a task to inspect its latest model review, follow a citation to the recorded tool result, or filter results by tool. **Export report** downloads a JSON snapshot of the request, task status, file actions, model checks and tool results. Review the file before sharing because tool results can contain project source and command output.

## Engineering controls

* **Repository map.** Ask a coding task to use `code_map` with a symbol or phrase. OpenAgent incrementally indexes Python, JS/JSX and TS/TSX into local SQLite FTS5 and returns up to five ranked source files with symbol locations. Indexes live under the local data directory.
* **MCP.** In Settings → Engineering settings, add a server name and Streamable HTTP endpoint, then save. Ask a task to list the server’s tools. OpenAgent shows the exact destination, tool and arguments before each call. For bearer authentication set `OPEN_AGENT_MCP_TOKEN_<SERVER>` in the backend process environment, replacing non-alphanumeric characters in the uppercase name with underscores. The server receives the approved arguments. Interactive OAuth and stdio transports are outside this version.
* **Python LSP.** Enable diagnostics to run the bundled Python language server after each approved Python write or replacement. Results appear in task evidence. Enable the separate TypeScript option for JS, JSX, TS and TSX. It uses the bundled TypeScript language server with automatic package acquisition disabled. Other languages continue to use named project checks.
* **Worktrees and checkpoints.** Select the worktree checkbox when starting a task from a clean Git repository root. OpenAgent records HEAD and edits a detached worktree. Restore opens a fresh worktree at that commit, ends the task and preserves the prior worktree for recovery. This isolates checkout changes; terminal processes still have your OS account permissions. Dependencies and ignored files are not copied.
* **Model routing.** Choose installed models separately for planning/review and coding/exploration. Empty selections use the existing default. File lookup and parsing run locally without inference.
* **Parallel verification.** Open Parallel verification on a task, discover checks, inspect the command and approve a run. A background verifier copies project sources, executes the selected check and asks a second model session to review the captured output. Its evidence applies to that copy. Dependencies, Git metadata and local environment files are excluded. Tests requiring those files can fail. Copying a changing directory is not an atomic filesystem snapshot.
* **Permissions.** On a pending named check, choose Always allow this check here to remember the project, directory, command and lifecycle scripts. Revoke the rule in Settings. A changed recipe requires approval again. Arbitrary shell commands continue to require individual approval.
* **Compaction.** Long task histories retain recent events, a bounded summary of earlier tool outcomes with event IDs, and earlier decisions and repair requests. The complete history remains in the task database.
* **Images.** In the chat composer, choose **+ → Upload image** to attach a JPEG, PNG or WebP image. You can also paste an image into the message field. Images are validated, resized and stored locally. The most recent image in the bounded conversation context is sent to the configured local model as a multimodal message. Use a vision-capable model for image interpretation.
