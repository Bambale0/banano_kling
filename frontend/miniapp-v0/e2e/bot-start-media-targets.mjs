// Exact media-target continuity and optional delivery/modal interaction.
// All bot, API and media transport is synthetic; no generation is requested.

import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdtempSync, symlinkSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { resolve, join } from 'node:path'
import { chromium } from 'playwright'
const root = mkdtempSync(join(tmpdir(), 'target-return-e2e-'))
symlinkSync(resolve('out'), join(root, 'mini-app'), 'dir')
const port = Number(process.env.BOT_START_MEDIA_E2E_PORT || 4187), origin = 'http://127.0.0.1:' + port, base = origin + '/mini-app/'
const server = spawn('python3', ['-m','http.server',String(port),'--bind','127.0.0.1','--directory',root], {stdio:'ignore'})
const video = readFileSync('e2e/fixtures/genjutsu-result.mp4')
const reference = 'https://example.test/reference.svg'
const bootstrap = {
  ok:true, telegram_id:424242, first_name:'E2E', last_name:'Target', telegram_username:'target',
  photo_url:'', referral_code:'E2ETARGET', profile_link:'',referral_link:'',channel_url:'',
  prompt_repeat_balance_rub:0,prompt_repeat_total_rub:0,bot_username:'test_bot',credits:125,is_admin:false,
  mini_app_url:base, actions:[],payment_packages:[],recent_tasks:[],saved_references:[],
  image_models:[{id:'banana_pro',label:'Nano Banana Pro',description:'Test',cost:1,ratios:['1:1'],qualities:['2K'],quality_costs:{'2K':1},max_references:8}],
  video_models:[{id:'v3_pro',label:'Kling 3 Pro',description:'Test',durations:[5],ratios:['16:9'],supports:['text','imgtxt'],costs:{'5':1}}],
}
const cases = [
  {label:'photo prompt',start:'prompt_41',kind:'prompt',id:41},
  {label:'video prompt',start:'prompt_42',kind:'prompt',id:42,video:true},
  {label:'photo trend',start:'prompt_43',kind:'prompt',id:43,trend:true},
  {label:'photo feed',start:'feed_44',kind:'feed',id:44},
  {label:'video feed',start:'feed_47',kind:'feed',id:47,video:true},
  {label:'photo remix',start:'remix_45',kind:'feed',id:45,remix:true},
  {label:'video remix',start:'remix_46',kind:'feed',id:46,video:true,remix:true},
  {label:'profile',start:'profile_AUTHOR',kind:'profile'},
]
let browser
try {
  const deadline=Date.now()+15000
  while(true) { try { if((await fetch(base)).ok) break } catch{}; if(Date.now()>deadline) throw Error('no export'); await new Promise(r=>setTimeout(r,100)) }
  browser=await chromium.launch({headless:true})
  for(const c of cases.filter(c => !c.trend).concat(cases.filter(c => c.trend))) {
    const context=await browser.newContext({viewport:{width:390,height:900},serviceWorkers:'block'})
    const page=await context.newPage()
    page.setDefaultTimeout(8000)
    let available=false
    const calls=[],errors=[],unexpected=[]
    page.on('pageerror',e=>errors.push(e.message))
    await page.addInitScript(()=>{
      window.__opened=[]
      window.Telegram={WebApp:{initData:'query_id=media-target-e2e',initDataUnsafe:{},ready(){},expand(){},
        openTelegramLink(url){window.__opened.push(url)},requestWriteAccess(){throw Error('native permission called')},
        onEvent(event,handler){window.addEventListener('fixture:'+event,handler)},
        offEvent(event,handler){window.removeEventListener('fixture:'+event,handler)}}}
    })
    const result='https://example.test/'+c.id+(c.video?'.mp4':'.svg')
    const promptText='Exact source prompt '+c.id
    const feed={id:c.id,task_id:'task-'+c.id,model:c.video?'v3_pro':'banana_pro',gen_type:c.video?'video':'image',
      result_url:result,preview_url:result,result_urls:[result],prompt:promptText,prompt_hidden:false,
      reference_images:c.remix&&!c.video?[reference]:[],reference_videos:[],references_hidden:false,feed_references_visible:true,
      likes_count:0,shares_count:0,comments_count:0,aspect_ratio:c.video?'16:9':'1:1',duration:5,scenario:'text',
      author:'Target Author',author_referral_code:'AUTHOR',is_mine:true,is_profile_visible:true,publication_scope:'feed',
      feed_interactions_enabled:true,remixes:0,score:0,created_at:'2026-10-06T00:00:00Z'}
    const prompt={id:c.id,title:'Media Target '+c.id,description:'Target-specific fixture',prompt_text:promptText,
      category:c.video?'video':'photo',tags:c.trend||c.video?['trend']:[],uses_count:0,likes:0,preview_url:null,
      model:c.video?'v3_pro':'banana_pro',author_id:1,status:'approved',
      generation_settings:{kind:c.video?'video':'image',user_input:'prompt',model:c.video?'v3_pro':'banana_pro',
        scenario:'text',ratio:c.video?'16:9':'1:1',quality:'2K',count:1,duration:5}}
    await page.route('**/*',async route=>{
      const req=route.request(),url=new URL(req.url())
      if(url.pathname.endsWith('/telegram-web-app.js')) return route.fulfill({contentType:'application/javascript',body:'// fixture'})
      if(url.hostname==='example.test') return route.fulfill(url.pathname.endsWith('.mp4')
        ?{contentType:'video/mp4',body:video}
        :{contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" fill="gold"/></svg>'})
      if(url.pathname.includes('/mini-app/api/')) {
        const path=url.pathname.split('/api/')[1],body=JSON.parse(req.postData()||'{}')
        calls.push({path,body})
        let data
        if(path==='bootstrap') data={...bootstrap,telegram_chat_available:available}
        else if(path==='prompts/detail') {assert.equal(body.prompt_id,c.id);data={ok:true,prompt}}
        else if(path==='feed/item') {assert.equal(body.gen_id,c.id);data={ok:true,feed_item:feed}}
        else if(path==='feed/profile') {assert.equal(body.referral_code,'AUTHOR');data={ok:true,profile:{referral_code:'AUTHOR',display_name:'Target Author',username:'target_author',photo_url:'',posts_count:0,likes_count:0,shares_count:0,remixes_count:0},feed:[]}}
        else if(path==='prompts') data={ok:true,prompts:[]}
        else if(path==='feed') data={ok:true,feed:[],models:[]}
        else if(path==='genjutsu'&&body.action==='availability') data={ok:true,visible:false}
        else if(path==='client-log') data={ok:true}
        else {unexpected.push(path);data={ok:false,error:'unexpected mocked path'}}
        return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)})
      }
      if(url.origin===origin&&req.method()==='GET') return route.continue()
      unexpected.push(url.href);return route.abort()
    })
    await page.goto(base+'?startapp='+c.start)
    const gate=page.locator('[role="dialog"][aria-labelledby="bot-write-access-title"]')
    if (!c.trend) await gate.waitFor()
    let marker
    if(c.kind==='profile') marker=page.getByText('Target Author',{exact:true}).first()
    else if(c.trend) marker=page.getByText('Media Target '+c.id,{exact:true}).first()
    else if(c.kind==='feed'&&!c.remix) {
      await page.getByRole('button',{name:'Закрыть',exact:true}).waitFor({state:'attached'})
      marker=c.video?page.locator('video[controls]'):page.locator('img[src="'+result+'"]').last()
    } else marker=page.getByPlaceholder(c.video
      ?'Опишите движение камеры, сцену, свет, ритм, физику движения и желаемый cinematic-эффект...'
      :'Опишите сцену, стиль, свет, камеру, детали персонажей и желаемый результат...')
    if(c.remix&&!c.video) marker=page.getByPlaceholder('Выберите, что изменить, и допишите детали. Остальное будет сохранено.')
    await marker.waitFor({state:'attached'})

    if(c.trend) {
      // The optional delivery offer must not compete with the real trend
      // dialog's focus trap, aria-hidden state, or pointer-event protections.
      await page.waitForLoadState('networkidle')
      assert.equal(await gate.count(),0,'Trend dialog must not be covered by optional delivery modal')
      const trendNode=await marker.elementHandle()
      const trendDialog=page.locator('[data-slot="dialog-content"]').filter({hasText:'Media Target '+c.id})
      await trendDialog.waitFor()
      const closeTrend=trendDialog.getByRole('button',{name:'Закрыть',exact:true})
      await closeTrend.click()
      await trendDialog.waitFor({state:'hidden'})
      await gate.waitFor()
      await gate.getByRole('button',{name:'Открыть бота',exact:true}).click()
      assert.equal((await page.evaluate(()=>window.__opened)).length,1,'Start works after trend closes')
      available=true
      await page.evaluate(()=>window.dispatchEvent(new Event('fixture:activated')))
      await gate.waitFor({state:'hidden'})
      assert.equal(page.url(),base+'?startapp='+c.start,'Start does not overwrite original trend URL')
      // The same link still resolves the same media target after Start.
      await page.goto(base+'?startapp='+c.start)
      await marker.waitFor()
      await page.waitForLoadState('networkidle')
      assert.equal(await gate.count(),0)
      assert.equal(await marker.innerText(),'Media Target '+c.id)
      await closeTrend.click()
      await trendDialog.waitFor({state:'hidden'})
      // Fresh denial of delivery tests Skip without granting it locally.
      available=false
      await page.goto(base+'?startapp='+c.start)
      await marker.waitFor()
      await page.waitForLoadState('networkidle')
      assert.equal(await gate.count(),0,'A reopened trend remains directly usable before Start')
      await closeTrend.click()
      await gate.waitFor()
      await gate.getByRole('button',{name:'Пропустить',exact:true}).click()
      await gate.waitFor({state:'hidden'})
      await page.getByRole('button',{name:'Получать в боте',exact:true}).waitFor()
      await page.goto(base+'?startapp='+c.start)
      await marker.waitFor()
      await page.waitForLoadState('networkidle')
      assert.equal(await gate.count(),0,'Skip still permits the exact original trend link')
      await closeTrend.click()
      await trendDialog.waitFor({state:'hidden'})
      await page.getByRole('button',{name:'Получать в боте',exact:true}).waitFor()
      assert.equal(await gate.count(),0,'Session dismissal persists after closing reopened trend')
      assert.ok(calls.filter(x=>x.path==='bootstrap').every(x=>x.body.start_param_fallback===c.start))
      assert.ok(calls.filter(x=>x.path==='prompts/detail').every(x=>x.body.prompt_id===c.id))
      assert.deepEqual(unexpected,[],'Trend path remains fully mocked')
      assert.deepEqual(errors,[],'Trend path has no browser errors')
      await trendNode.dispose()
      console.log('PASS photo trend: exact source target usable without competing modal; close reveals optional Start/Skip; original link reopens after Start and Skip')
      await context.close()
      continue
    }

    if(c.kind==='prompt'&&!c.trend||c.remix&&c.video) assert.equal(await marker.inputValue(),promptText,c.label+' loaded source prompt')
    const node=await marker.elementHandle(),before=page.url()
    if(c.remix&&!c.video) assert.ok(await page.locator('img[src="'+reference+'"]').count()>0,'remix reference loaded')
    await page.waitForLoadState('networkidle')
    await gate.locator('button').filter({hasText:'Открыть бота'}).click()
    assert.equal((await page.evaluate(()=>window.__opened)).length,1)
    available=true
    await page.evaluate(()=>window.dispatchEvent(new Event('fixture:activated')))
    await gate.waitFor({state:'hidden'})
    for(const event of ['focus','visibilitychange']) {
      const reply=page.waitForResponse(r=>r.url().endsWith('/bootstrap'))
      await page.evaluate(e=>e==='focus'?window.dispatchEvent(new Event(e)):document.dispatchEvent(new Event(e)),event)
      await reply
      await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))))
      assert.equal(await node.evaluate(el=>el.isConnected),true,c.label+' preserves target node after '+event)
    }
    assert.equal(page.url(),before,c.label+' URL unchanged')
    assert.ok(calls.filter(x=>x.path==='bootstrap').every(x=>x.body.start_param_fallback===c.start),c.label+' ID remains in bootstrap')
    if(c.kind==='prompt'&&!c.trend||c.remix&&c.video) assert.equal(await marker.inputValue(),promptText)
    if(c.remix&&!c.video) assert.ok(await page.locator('img[src="'+reference+'"]').count()>0,'reference survives')
    assert.deepEqual(unexpected,[],c.label+' unexpected requests')
    assert.deepEqual(errors,[],c.label+' browser errors')
    console.log('PASS '+c.label+': '+c.start+' target ID, source view/DOM, URL retained after Start + activated/focus/visibility; no generation')
    await context.close()
  }
} finally {await browser?.close();server.kill('SIGTERM');rmSync(root,{recursive:true,force:true})}
