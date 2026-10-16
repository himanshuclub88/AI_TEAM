# Orbit AI Team

**A local-first, multi-agent AI workspace for turning project ideas into code, documentation, and test plans.**

Orbit AI Team coordinates specialized AI agents through a project workflow and organizes generated artifacts in a Playground where you can inspect project files.

> **Note:** Capabilities depend on the current backend implementation, configured language model, and tools installed on your computer. This README distinguishes the described workflow from suggested future features.

## What Orbit AI Team can do

### Coordinate specialized agents

- **Manager:** Coordinates the workflow and delegates tasks.
- **Researcher:** Helps analyze the request and organize requirements.
- **Architect:** Plans the structure and technical approach.
- **Developer:** Generates application source files and supporting documentation.
- **Tester:** Reviews generated files, prepares test plans, and runs checks supported by the environment.

The quality and completeness of results depend on the request, model output, and available tools.

### Generate project files

Depending on the task and agent permissions, Orbit can generate artifacts such as:

- HTML, CSS, and JavaScript for web applications
- Python scripts and utilities
- Markdown documentation and test plans
- JSON configuration or project metadata
- Other supported project files

### Browse projects in Playground

The Playground lets you:

- Browse available projects.
- Select a project and view its files.
- Open a file to inspect its contents.
- Review source code, documentation, and test artifacts in one workspace.

Previewing a file does not, by itself, prove that the application works correctly.

### Review and test generated code

The Tester can inspect source files, create a test plan, and run checks available in your local environment. Depending on the project, these may include JavaScript syntax validation and project-specific checks.

**Skipped checks are not passed checks.** For example, if Node.js is not installed or not available on `PATH`, JavaScript syntax validation may be skipped. A written test plan is not evidence that the listed functional tests were executed.

### Work locally

Orbit is designed around a local development workflow, with a Python/FastAPI backend and a browser-based frontend. Generated project files can be kept in your local workspace.

Local execution does not necessarily mean every model request stays on your computer. If you configure a hosted LLM provider, prompts and relevant context may be sent to that provider. Review your configuration before using sensitive data.

## Example projects

You can describe projects in natural language, such as:

- **To-do list:** A responsive task list with add, delete, completion, and browser `localStorage` persistence.
- **Hotel administration dashboard:** Screens for rooms, guests, bookings, staff, search, and dashboard metrics.
- **Small web tools:** Frontends built with HTML, CSS, and JavaScript.
- **Python utilities:** Scripts with supporting documentation and test plans.

These are example tasks, not a guarantee that every generated feature will work without review.

## Typical workflow

1. **Describe the project.** Explain its purpose, required features, and technical preferences.
2. **Let the Manager coordinate the work.** The workflow delegates tasks to the relevant agent roles.
3. **Inspect the output.** Open the project in Playground and review its files.
4. **Run available checks.** Check which tests passed, failed, or were skipped.
5. **Test the application yourself.** Launch it using the project's instructions and try important user flows.
6. **Iterate.** Give specific feedback and ask for targeted changes.

## Technology

The current setup discussed for Orbit includes:

- **Frontend:** HTML, CSS, JavaScript
- **Backend:** Python, FastAPI
- **Validation/models:** Pydantic
- **AI integration:** A configurable LLM wrapper and configuration
- **Workspace:** Local project files and generated artifacts

Exact dependencies, storage details, and startup commands should be confirmed against the current repository.

## Running locally

Use the commands documented in your repository. A typical setup sequence is:

1. Open a terminal in the backend directory.
2. Activate the project's Python virtual environment.
3. Install dependencies from the project's dependency file.
4. Configure the LLM settings required by your `config.py` and `llm.py`.
5. Start the FastAPI server using the command configured for your project.
6. Open the frontend using the method configured by your application.

The exact startup command, port, and dependency list are intentionally not guessed here. Add those details from your current repository before publishing this README.

## Limitations to keep in mind

- **Generated code needs review.** Agents can make mistakes or misunderstand requirements.
- **Test plans are not executed tests.** Confirm which checks actually ran.
- **Tool availability matters.** Automated checks may be skipped when runtimes such as Node.js are missing.
- **Features may be incomplete.** Test core user flows, persistence, error handling, and responsive layouts.
- **Model quality varies.** Results depend on the configured model and its output.
- **Keep backups.** Commit changes or back up files before accepting large generated edits.
- **Provider privacy depends on configuration.** A local app may still use a remote model API.

## Suggested extra features

The following are ideas for future improvements, not claims that they already exist:

- **Live agent progress:** Display each agent's phase and current status.
- **Diff viewer:** Review file changes before accepting them.
- **Run and preview controls:** Launch generated projects when their runtimes are supported.
- **Test dashboard:** Separate passed, failed, and skipped checks and show logs.
- **Dependency detection:** Identify missing tools such as Node.js and explain how to install them.
- **Project checkpoints:** Compare or restore previous versions.
- **Agent activity log:** Track delegation, decisions, file writes, and test outcomes.
- **Project export:** Package a project with its documentation for backup or sharing.
- **Configurable permissions:** Define file permissions per agent and record which agent changed each file.

## Contributing

1. Back up current files or commit them to version control.
2. Prefer focused patches over replacing entire modules.
3. Preserve existing agent roles and prompts unless intentionally changing them.
4. Run syntax checks and the available test suite.
5. Report clearly what passed, failed, or could not be tested.

## License

Add the license that applies to this project before publishing or distributing it.
