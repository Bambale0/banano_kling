import fs from 'node:fs'
import path from 'node:path'
import ts from 'typescript'

// Official CI checks the live declaration; restricted local runs use the approved extracted fixture.
const inputPath = process.env.WAN_SUBMIT_FIXTURE === '1'
  ? '__tests__/fixtures/wan-submit-prompt.txt' : 'lib/api.ts'
const source = ts.createSourceFile('api.ts', fs.readFileSync(path.join(process.cwd(), inputPath), 'utf8'), ts.ScriptTarget.Latest, true)
const declarations = source.statements.filter((node): node is ts.FunctionDeclaration => ts.isFunctionDeclaration(node) && node.name?.text === 'submitPrompt')
if (declarations.length !== 1) throw new Error('Expected exactly one submitPrompt declaration')
const code = ts.transpileModule(declarations[0].getText(source).replace(/^export\s+/, ''), { compilerOptions: { target: ts.ScriptTarget.ES2020 } }).outputText
function actualSubmit(initData: string, postJson: jest.Mock) {
  return new Function('getInitData', 'postJson', `${code}; return submitPrompt;`)(() => initData, postJson)
}

test.each(['wan_3', 'wan_3_prime'])('actual submitPrompt preserves the full %s private recipe and explicit slot bindings on the wire', async model => {
  const settings = {
    wan3_recipe: { model, prompt: 'Use Image1 and Video1.', scenario: 'reference', duration: 5, audio: false, nsfw_checker: false, seed: 0, reference_image_urls: ['https://owned.test/photo'], reference_video_urls: ['https://owned.test/video'] },
    wan3_replacement_keys: ['image:0'],
  }
  const original = JSON.stringify(settings)
  const post = jest.fn().mockResolvedValue({ ok: true, prompt: { id: 101, model } })
  const result = await actualSubmit('signed-synthetic', post)({ title: 'Synthetic', description: '', promptText: settings.wan3_recipe.prompt, previewUrl: 'https://owned.test/preview', model, tags: ['trend-video'], generationSettings: settings })
  expect(post).toHaveBeenCalledTimes(1)
  expect(post).toHaveBeenCalledWith('prompts/submit', { init_data: 'signed-synthetic', title: 'Synthetic', description: '', prompt_text: settings.wan3_recipe.prompt, preview_url: 'https://owned.test/preview', model, tags: ['trend-video'], generation_settings: settings })
  expect(JSON.stringify(settings)).toBe(original)
  expect(result).toEqual({ id: 101, model })
})

test('actual submitPrompt refuses unauthenticated publication before transport', async () => {
  const post = jest.fn()
  await expect(actualSubmit('', post)({ title: 'Synthetic', description: '', promptText: 'A landscape' })).rejects.toThrow('Telegram')
  expect(post).not.toHaveBeenCalled()
})
