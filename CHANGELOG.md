# Changelog

## 0.3.0 — in development

### Batch 1: project data

- Add database schema versioning with a nondestructive v0.2 migration and rejection of newer schemas.
- Add checksummed project archives using SQLite's backup API, plus restore into an empty workspace.
- Expose `backup_project` and `project_data_info` through the permission-controlled research MCP service.
- Verify WAL backup, restored evidence/job files, version compatibility, archive tampering, traversal and symlink rejection.

## 0.2.0

Interactive Pi CLI with project-scoped research MCP tools, evidence and memory, bounded experiment jobs, npm distribution and standalone installers. See [release notes](docs/releases/v0.2.0.md).
