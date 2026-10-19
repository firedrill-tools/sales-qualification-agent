import { fileURLToPath } from 'node:url';
import { resolve, join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { ApplicationError, commandMain, invokeCLI, privateDirectory } from './adapter-runtime.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const cases = new Set(['starter', 'duplicate-email']);

export async function runApplication(input, parameters, signal, invocation) {
  if (Object.keys(input).some(key => !['caseId', 'task', 'allowWrites'].includes(key)) || !cases.has(input.caseId) ||
      typeof input.task !== 'string' || !input.task.trim() || input.task.length > 12000 || input.task.includes('\0') ||
      typeof input.allowWrites !== 'boolean') {
    throw new Error('Select a reviewed case, bounded task and explicit independent boolean write permission.');
  }
  const directory = await privateDirectory(root, invocation);
  const state = join(directory, 'workspace.json');
  const cli = ['uv', 'run', '--locked', '--no-sync', 'qualify-lead'];
  try {
    await invokeCLI([...cli, '--init-case', input.caseId, '--workspace', state], { cwd: root, signal });
    const argv = [...cli, '--mode', 'synthetic', '--workspace', state, '--request-id', randomUUID()];
    if (input.allowWrites) argv.push('--allow-write');
    if (parameters.model) argv.push('--model', parameters.model);
    argv.push(input.task);
    const output = await invokeCLI(argv, { cwd: root, signal, timeoutMs: 270000 });
    return { application: output, localState: { directory, workspaceFile: state } };
  } catch (error) {
    if (error instanceof ApplicationError) error.evidence.runDirectory = directory;
    throw error;
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await commandMain(runApplication);
}
