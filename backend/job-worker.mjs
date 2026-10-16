import { parentPort, workerData } from 'node:worker_threads';
import { Store } from './store.mjs';
import { executeWorkflow } from './engine.mjs';

const store = new Store(workerData.dataDir);
try {
  const result = await executeWorkflow(store, workerData.workflow, step => parentPort.postMessage({ type: 'progress', step }));
  parentPort.postMessage({ type: 'result', result });
} catch (error) {
  parentPort.postMessage({ type: 'failed', message: error.message });
} finally { store.close(); }
