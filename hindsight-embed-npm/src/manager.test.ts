import { describe, it, expect } from 'vitest';
import { HindsightEmbedManager } from './manager.js';

describe('HindsightEmbedManager construction', () => {
  it('defaults base URL to http://127.0.0.1:8888', () => {
    const mgr = new HindsightEmbedManager();
    expect(mgr.getBaseUrl()).toBe('http://127.0.0.1:8888');
    expect(mgr.getProfile()).toBe('default');
  });

  it('honours custom profile, port, and host', () => {
    const mgr = new HindsightEmbedManager({ profile: 'app', port: 9077, host: '0.0.0.0' });
    expect(mgr.getProfile()).toBe('app');
    expect(mgr.getBaseUrl()).toBe('http://0.0.0.0:9077');
  });

  it('accepts open env pass-through without complaining about unknown keys', () => {
    const mgr = new HindsightEmbedManager({
      env: {
        HINDSIGHT_API_LLM_PROVIDER: 'openai',
        HINDSIGHT_API_LLM_MODEL: 'gpt-4o-mini',
        // A field that does not exist today — should still be accepted
        HINDSIGHT_FUTURE_FLAG: 'enabled',
      },
    });
    expect(mgr).toBeInstanceOf(HindsightEmbedManager);
  });

  it('exposes checkHealth that returns false when no daemon is running', async () => {
    // Random high port that nothing is listening on.
    const mgr = new HindsightEmbedManager({ port: 1, readyTimeoutMs: 100 });
    const healthy = await mgr.checkHealth();
    expect(healthy).toBe(false);
  });
});
