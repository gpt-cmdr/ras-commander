# Remote Executor Reference Documentation

This folder contains detailed reference documentation for the remote-executor subagent.

## Files

### worker-configuration.md
Complete configuration guide for all worker types:
- **PsExec Worker** - Windows remote execution (Group Policy, Registry, network shares)
- **Docker Worker** - Container execution over SSH
- **Local Worker** - Parallel local execution
- **SSH Worker** - Direct SSH execution (stub)
- **WinRM Worker** - Windows Remote Management (stub)
- **Slurm Worker** - HPC cluster execution (stub)
- **AWS EC2 Worker** - AWS cloud execution (stub)
- **Azure Worker** - Azure cloud execution (stub)

Use this when:
- Setting up a new worker type
- Configuring remote machines
- Understanding worker capabilities and requirements

### common-issues.md
Troubleshooting guide for remote execution problems:
- **PsExec Worker Issues** - Silent failures, hangs, access denied
- **Docker Worker Issues** - Connection problems, authentication
- **Network and Connectivity** - Host unreachable, share disconnects
- **Permission and Security** - UAC, Windows Defender, firewall
- **HEC-RAS Execution** - HDF not created, result differences, timeouts

Use this when:
- Debugging execution failures
- Diagnosing permission errors
- Resolving network issues
- Understanding error messages

## Quick Reference

### Critical PsExec Configuration
```python
worker = init_ras_worker(
    worker_type='psexec',
    hostname='192.168.1.100',
    session_id=2,  # CRITICAL: Query with 'query session /server:HOST'
    remote_share=r'\\192.168.1.100\RAS_Share',
    hecras_version='6.5'
)
```

### Most Common Issues

1. **HEC-RAS doesn't execute** → Check `session_id=2` (not `system_account=True`)
2. **Access denied** → Set Registry key `LocalAccountTokenFilterPolicy=1`
3. **PsExec hangs** → Configure Group Policy (3 policies)
4. **Network path not found** → Check Remote Registry service running
5. **Docker connection failed** → Verify SSH key permissions (chmod 600)

## Related Documentation

- **Parent Subagent**: `.claude/subagents/remote-executor.md` - Main subagent file
- **Implementation Guide**: `ras_commander/remote/AGENTS.md` - Module structure and coding patterns
- **Critical Config**: `.claude/rules/hec-ras/remote.md` - Session ID requirements
- **Example Notebook**: `examples/23_remote_execution_psexec.ipynb` - Working example
