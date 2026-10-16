const base = `http://127.0.0.1:${Number(process.env.PORT || 4173)}`;
try {
  const health = await fetch(base+'/api/health',{signal:AbortSignal.timeout(2000)}).then(r=>r.json());
  if (health.data?.mode !== 'live') throw Error('该端口不是本项目的真实后端');
  const session = await fetch(base+'/api/auth/local-session',{method:'POST',headers:{Origin:base,'Content-Type':'application/json'},body:'{}'});
  if (!session.ok) throw Error('自动会话已关闭，请在启动终端按Ctrl+C停止');
  const cookie = session.headers.get('set-cookie')?.split(';')[0];
  const response = await fetch(base+'/api/governance/shutdown',{method:'POST',headers:{Cookie:cookie,Origin:base,'Content-Type':'application/json'},body:'{}'});
  const result = await response.json();
  if (!response.ok) throw Error(result.message);
  console.log(result.message);
} catch(error) { console.error('无法停止服务：'+error.message); process.exitCode=1; }
