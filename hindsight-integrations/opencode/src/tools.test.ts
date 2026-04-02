import { describe, it, expect, vi } from 'vitest';
import { createTools } from './tools.js';
import type { HindsightConfig } from './config.js';

function makeConfig(overrides: Partial<HindsightConfig> = {}): HindsightConfig {
    return {
        autoRecall: true,
        recallBudget: 'mid',
        recallMaxTokens: 1024,
        recallTypes: ['world', 'experience'],
        recallContextTurns: 1,
        recallMaxQueryChars: 800,
        recallPromptPreamble: '',
        autoRetain: true,
        retainMode: 'full-session',
        retainEveryNTurns: 10,
        retainOverlapTurns: 2,
        retainContext: 'opencode',
        retainTags: [],
        retainMetadata: {},
        hindsightApiUrl: null,
        hindsightApiToken: null,
        bankId: null,
        bankIdPrefix: '',
        dynamicBankId: false,
        dynamicBankGranularity: ['agent', 'project'],
        bankMission: '',
        retainMission: null,
        agentName: 'opencode',
        debug: false,
        ...overrides,
    };
}

const mockContext = {
    sessionID: 'sess-1',
    messageID: 'msg-1',
    agent: 'default',
    directory: '/tmp',
    worktree: '/tmp',
    abort: new AbortController().signal,
    metadata: vi.fn(),
    ask: vi.fn(),
};

describe('createTools', () => {
    it('creates all three tools', () => {
        const client = { retain: vi.fn(), recall: vi.fn(), reflect: vi.fn() } as any;
        const tools = createTools(client, 'test-bank', makeConfig());

        expect(tools.hindsight_retain).toBeDefined();
        expect(tools.hindsight_recall).toBeDefined();
        expect(tools.hindsight_reflect).toBeDefined();
    });

    it('all tools have description and execute', () => {
        const client = { retain: vi.fn(), recall: vi.fn(), reflect: vi.fn() } as any;
        const tools = createTools(client, 'test-bank', makeConfig());

        for (const tool of Object.values(tools)) {
            expect(tool.description).toBeTruthy();
            expect(typeof tool.execute).toBe('function');
        }
    });

    describe('hindsight_retain', () => {
        it('calls client.retain with correct bank and content', async () => {
            const client = {
                retain: vi.fn().mockResolvedValue({}),
                recall: vi.fn(),
                reflect: vi.fn(),
            } as any;
            const tools = createTools(client, 'test-bank', makeConfig());

            const result = await tools.hindsight_retain.execute(
                { content: 'User likes TypeScript' },
                mockContext,
            );

            expect(client.retain).toHaveBeenCalledWith('test-bank', 'User likes TypeScript', {
                context: 'opencode',
                tags: undefined,
                metadata: undefined,
            });
            expect(result).toBe('Memory stored successfully.');
        });

        it('passes optional context', async () => {
            const client = { retain: vi.fn().mockResolvedValue({}), recall: vi.fn(), reflect: vi.fn() } as any;
            const tools = createTools(client, 'test-bank', makeConfig());

            await tools.hindsight_retain.execute(
                { content: 'Fact', context: 'from conversation' },
                mockContext,
            );

            expect(client.retain).toHaveBeenCalledWith('test-bank', 'Fact', {
                context: 'from conversation',
                tags: undefined,
                metadata: undefined,
            });
        });

        it('includes tags and metadata from config', async () => {
            const client = { retain: vi.fn().mockResolvedValue({}), recall: vi.fn(), reflect: vi.fn() } as any;
            const config = makeConfig({
                retainTags: ['coding'],
                retainMetadata: { source: 'opencode' },
            });
            const tools = createTools(client, 'test-bank', config);

            await tools.hindsight_retain.execute({ content: 'Fact' }, mockContext);

            expect(client.retain).toHaveBeenCalledWith('test-bank', 'Fact', {
                context: 'opencode',
                tags: ['coding'],
                metadata: { source: 'opencode' },
            });
        });
    });

    describe('hindsight_recall', () => {
        it('calls client.recall and formats results', async () => {
            const client = {
                retain: vi.fn(),
                recall: vi.fn().mockResolvedValue({
                    results: [
                        { text: 'User likes Python', type: 'world', mentioned_at: '2025-01-01' },
                    ],
                }),
                reflect: vi.fn(),
            } as any;
            const tools = createTools(client, 'test-bank', makeConfig());

            const result = await tools.hindsight_recall.execute(
                { query: 'user preferences' },
                mockContext,
            );

            expect(client.recall).toHaveBeenCalledWith('test-bank', 'user preferences', {
                budget: 'mid',
                maxTokens: 1024,
                types: ['world', 'experience'],
            });
            expect(result).toContain('User likes Python');
            expect(result).toContain('[world]');
        });

        it('returns no-results message when empty', async () => {
            const client = {
                retain: vi.fn(),
                recall: vi.fn().mockResolvedValue({ results: [] }),
                reflect: vi.fn(),
            } as any;
            const tools = createTools(client, 'test-bank', makeConfig());

            const result = await tools.hindsight_recall.execute({ query: 'unknown' }, mockContext);
            expect(result).toBe('No relevant memories found.');
        });

        it('uses config budget settings', async () => {
            const client = {
                retain: vi.fn(),
                recall: vi.fn().mockResolvedValue({ results: [] }),
                reflect: vi.fn(),
            } as any;
            const config = makeConfig({ recallBudget: 'high', recallMaxTokens: 4096 });
            const tools = createTools(client, 'test-bank', config);

            await tools.hindsight_recall.execute({ query: 'test' }, mockContext);

            expect(client.recall).toHaveBeenCalledWith('test-bank', 'test', {
                budget: 'high',
                maxTokens: 4096,
                types: ['world', 'experience'],
            });
        });
    });

    describe('hindsight_reflect', () => {
        it('calls client.reflect and returns text', async () => {
            const client = {
                retain: vi.fn(),
                recall: vi.fn(),
                reflect: vi.fn().mockResolvedValue({ text: 'The user is a Python developer.' }),
            } as any;
            const tools = createTools(client, 'test-bank', makeConfig());

            const result = await tools.hindsight_reflect.execute(
                { query: 'What do I know about this user?' },
                mockContext,
            );

            expect(client.reflect).toHaveBeenCalledWith(
                'test-bank',
                'What do I know about this user?',
                { context: undefined, budget: 'mid' },
            );
            expect(result).toBe('The user is a Python developer.');
        });

        it('returns fallback when no text', async () => {
            const client = {
                retain: vi.fn(),
                recall: vi.fn(),
                reflect: vi.fn().mockResolvedValue({ text: '' }),
            } as any;
            const tools = createTools(client, 'test-bank', makeConfig());

            const result = await tools.hindsight_reflect.execute(
                { query: 'something' },
                mockContext,
            );
            expect(result).toBe('No relevant information found to reflect on.');
        });

        it('passes context to reflect', async () => {
            const client = {
                retain: vi.fn(),
                recall: vi.fn(),
                reflect: vi.fn().mockResolvedValue({ text: 'Answer' }),
            } as any;
            const tools = createTools(client, 'test-bank', makeConfig());

            await tools.hindsight_reflect.execute(
                { query: 'Q', context: 'We are building an app' },
                mockContext,
            );

            expect(client.reflect).toHaveBeenCalledWith('test-bank', 'Q', {
                context: 'We are building an app',
                budget: 'mid',
            });
        });
    });

    describe('error propagation', () => {
        it('propagates retain errors', async () => {
            const client = {
                retain: vi.fn().mockRejectedValue(new Error('Network error')),
                recall: vi.fn(),
                reflect: vi.fn(),
            } as any;
            const tools = createTools(client, 'test-bank', makeConfig());

            await expect(
                tools.hindsight_retain.execute({ content: 'test' }, mockContext),
            ).rejects.toThrow('Network error');
        });

        it('propagates recall errors', async () => {
            const client = {
                retain: vi.fn(),
                recall: vi.fn().mockRejectedValue(new Error('Timeout')),
                reflect: vi.fn(),
            } as any;
            const tools = createTools(client, 'test-bank', makeConfig());

            await expect(
                tools.hindsight_recall.execute({ query: 'test' }, mockContext),
            ).rejects.toThrow('Timeout');
        });

        it('propagates reflect errors', async () => {
            const client = {
                retain: vi.fn(),
                recall: vi.fn(),
                reflect: vi.fn().mockRejectedValue(new Error('Server error')),
            } as any;
            const tools = createTools(client, 'test-bank', makeConfig());

            await expect(
                tools.hindsight_reflect.execute({ query: 'test' }, mockContext),
            ).rejects.toThrow('Server error');
        });
    });

    it('always uses constructor bankId', async () => {
        const client = {
            retain: vi.fn().mockResolvedValue({}),
            recall: vi.fn().mockResolvedValue({ results: [] }),
            reflect: vi.fn().mockResolvedValue({ text: 'ok' }),
        } as any;
        const tools = createTools(client, 'fixed-bank', makeConfig());

        await tools.hindsight_retain.execute({ content: 'x' }, mockContext);
        await tools.hindsight_recall.execute({ query: 'x' }, mockContext);
        await tools.hindsight_reflect.execute({ query: 'x' }, mockContext);

        expect(client.retain.mock.calls[0][0]).toBe('fixed-bank');
        expect(client.recall.mock.calls[0][0]).toBe('fixed-bank');
        expect(client.reflect.mock.calls[0][0]).toBe('fixed-bank');
    });
});
