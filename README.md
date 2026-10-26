# research-tools

A Claude Code plugin marketplace for research workflows.

## Install

```
/plugin marketplace add <path-or-git-url-to-this-repo>
/plugin install <plugin-name>@research-tools
```

## Adding a plugin

1. Create `plugins/<plugin-name>/` with a `.claude-plugin/plugin.json` and its
   components (`skills/`, `commands/`, `agents/`, `hooks/`, `.mcp.json`).
2. Add an entry to `.claude-plugin/marketplace.json`:

   ```json
   {
     "name": "<plugin-name>",
     "source": "./plugins/<plugin-name>",
     "description": "What it does"
   }
   ```

3. Check it with `claude plugin validate .`
