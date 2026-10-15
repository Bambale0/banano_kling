// Live category showcase end-to-end regression with synthetic Telegram/initData.
// No real users, payments, providers or production networking.
// Tests mobile carousels, paginated folder, lazy muted video and private repeat UI.
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { chromium, devices } from 'playwright'

const port = 4328
const base = 'http://127.0.0.1:' + port
const server = spawn('python3', ['-m','http.server',String(port),'--bind','127.0.0.1','--directory','.e2e-server'], { stdio:'ignore' })
let browser
const photo = {
  id: 1401, title:'Свечи с возрастом', description:'Свой торт и число',
  category:'photo', tags:['trend'], status:'approved', model:null,
  prompt_text:'', likes:0, uses_count:0, author_id:999,
  preview_url:'/uploads/photo.jpg', repeat_cost:4,
  successful_runs_count:328,
  generation_settings:{kind:'image', ratio:'1:1', preview_type:'image',
    reference_count:1, user_fields:[{key:'Возраст',label:'Возраст',type:'number',required:true,max_length:160}]}
}
const video = {
  ...photo, id: 1402, title:'Живое видео', category:'video',
  tags:['trend','trend-video'], preview_url:'/uploads/motion.mp4', repeat_cost:14,
  generation_settings:{kind:'video',ratio:'9:16',preview_type:'video',reference_count:1},
  badge:'new'
}
const legacyVideo = {
  ...video, id:1404, title:'Видео без расширения',
  preview_url:'/uploads/legacy-video?auth=synthetic',
  generation_settings:{kind:'video', ratio:'9:16', reference_count:1},
  badge:undefined
}
let legacyPromptRequests = 0
let adminMode = false
const category = {
  id: 101, title:'День рождения', emoji:'🧁', sort_order:0, revision:3,
  is_visible:true, total:4, items:[photo,video,legacyVideo]
}
const reels = {
  id: 102, title:'Липсинги', emoji:'🎵', sort_order:1,revision:1,
  is_visible:true,total:1,items:[video]
}
try {
  let ready = false
  for (let i=0;i<50;i++){
    try { ready=(await fetch(base+'/mini-app/')).ok } catch {}
    if(ready)break
    await new Promise(r=>setTimeout(r,100))
  }
  assert.equal(ready,true,'static export available')
  browser=await chromium.launch({headless:true})
  const context=await browser.newContext({...devices['iPhone 13']})
  const page=await context.newPage()
  page.setDefaultTimeout(20000)
  const errors=[]
  page.on('pageerror',err=>errors.push(err.message))
  await context.addInitScript(() => {
    window.Telegram={ WebApp: {
      initData:'query_id=synthetic-live-catalog', initDataUnsafe:{},
      ready(){}, expand(){}, onEvent(){},offEvent(){},
      openTelegramLink(){}, platform:'ios',
    }}
  })
  await context.route('**/*',async route=>{
    const url=new URL(route.request().url())
    if(url.pathname.endsWith('/telegram-web-app.js'))
      return route.fulfill({contentType:'application/javascript',body:'// test fixture'})
    if(url.pathname.endsWith('/uploads/motion.mp4') || url.pathname.endsWith('/uploads/legacy-video'))
      return route.fulfill({contentType:'video/mp4',body:readFileSync('e2e/fixtures/seedance25-source.mp4')})
    if(url.pathname.endsWith('/uploads/photo.jpg'))
      return route.fulfill({contentType:'image/jpeg',body:Buffer.from([255,216,255,224,0,16,74,70,73,70])})
    if(url.pathname.includes('/mini-app/api/')){
      let body={ok:true}
      if(url.pathname.endsWith('/bootstrap')){
        body={ok:true, telegram_id:1601, first_name:'QA', credits:220, is_admin:adminMode,
          telegram_chat_available:true, telegram_bot_start_required:false, bot_username:'qa_bot',
          mini_app_url:base+'/mini-app/', image_models:[{id:'banana_pro',label:'Nano Banana Pro',ratios:['1:1'], qualities:['2K'], max_references:8,costs:{}}],
          video_models:[{id:'seedance_2_5',label:'Seedance 2.5', supports:['imgtxt'], ratios:['9:16'],durations:[10],costs:{}}],
          recent_tasks:[], saved_references:[], actions:[], payment_packages:[]}
      }else if(url.pathname.endsWith('/trends/catalog')){
        body={ok:true,categories:[category,reels]}
      }else if(url.pathname.endsWith('/trends/category')){
        const p=route.request().postDataJSON()
        body={ok:true, category:{...category,items:undefined},page:p.page,total:4,has_more:p.page===1,
          items:p.page===1?[photo,video,legacyVideo]:[{...photo,id:1403,title:'Другой праздник'}]}
      }else if(url.pathname.endsWith('/admin/trends/categories')){
        const p=route.request().postDataJSON()
        if(p.op==='history') body={ok:true,result:[{
          id:'test-history',actor_telegram_id:999999999,action:'create',
          category_id:101,trend_id:null,created_at:'2026-10-15 09:00:00',
          before:null,after:{id:101,title:'День рождения',emoji:'🧁'}
        }]}
        else if(p.op==='search_trends') body={ok:true,result:{items:[],page:1,total:0,has_more:false}}
        else throw new Error('Unexpected mutation in read-only browser E2E: '+p.op)
      }else if(url.pathname.endsWith('/prompts')){
        legacyPromptRequests += 1
        body={ok:true,prompts:[photo,video]}
      }else if(url.pathname.endsWith('/feed')){
        body={ok:true,feed:[],models:[]}
      }else if(url.pathname.endsWith('/genjutsu')){
        body={ok:true,items:[],visible:false}
      }else if(url.pathname.endsWith('/prompts/detail')){
        body={ok:true,prompt:photo}
      }
      return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)})
    }
    if(url.origin===base) return route.continue()
    return route.abort()
  })
  await page.goto(base+'/mini-app/?tgWebAppData=query_id%3Dfixture',{waitUntil:'networkidle'})
  await page.getByRole('button',{name:'Все тренды категории День рождения'}).waitFor()
  assert.equal(legacyPromptRequests, 0, 'A successful catalog must not download and convert legacy grids')
  assert.equal(await page.getByText('Новинка',{exact:true}).count(),2)
  assert.equal(await page.getByRole('button',{name:'Все тренды категории Липсинги'}).count(),1)
  const live=page.getByRole('button',{name:'Открыть тренд Живое видео'}).first()
  await live.waitFor()
  assert.match(await live.innerText(),/328 повторов/, 'New live tiles must display actual completed repeats')
  const videoTag=live.locator('video')
  await videoTag.waitFor()
  assert.equal(await videoTag.evaluate(video => video.muted), true)
  const noExtension=page.getByRole('button',{name:'Открыть тренд Видео без расширения'}).first()
  await noExtension.locator('video').waitFor()
  await page.getByRole('button',{name:'Все тренды категории День рождения'}).click()
  await page.getByRole('button',{name:'Показать ещё'}).click()
  await page.getByRole('button',{name:'Открыть тренд Другой праздник'}).waitFor()
  await page.getByRole('button',{name:'Открыть тренд Свечи с возрастом'}).click()
  await page.getByRole('dialog').getByText('✅ Успешных повторов: 328').waitFor()
  await page.getByRole('dialog').getByRole('button',{name:/Повторить/}).click()
  const repeat = page.getByRole('dialog')
  await repeat.getByText('Персонализируйте шаблон',{exact:true}).waitFor()
  await repeat.getByRole('button',{name:/Сгенерировать/}).waitFor()
  assert.equal(await repeat.locator('input[type="file"]').count(),1)
  assert.equal(await repeat.getByLabel('Возраст *').count(),1)
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true)
  // Verify real wiring from the new showcase to existing admin edit/deactivate
  // controls, not just a standalone component mock. No mutation is performed.
  adminMode = true
  await page.reload({waitUntil:'networkidle'})
  await page.getByRole('button',{name:'Категории',exact:true}).waitFor()
  await page.getByRole('button',{name:'Открыть тренд Свечи с возрастом'}).click()
  const adminPreview = page.getByRole('dialog')
  await adminPreview.getByRole('button',{name:'Редактировать'}).click()
  await page.getByRole('dialog').getByText('Редактировать',{exact:true}).waitFor()
  await page.getByRole('dialog').getByRole('button',{name:'Close'}).click()
  await page.getByRole('button',{name:'Открыть тренд Свечи с возрастом'}).click()
  await page.getByRole('dialog').getByRole('button',{name:'Убрать тренд'}).waitFor()
  await page.getByRole('dialog').getByRole('button',{name:'Close'}).click()
  await page.getByRole('button',{name:'Категории',exact:true}).click()
  const manager=page.getByRole('dialog')
  await manager.getByRole('button',{name:'Показать историю'}).click()
  await manager.getByText('create · Telegram 999999999').waitFor()
  await manager.getByText('Посмотреть до и после').click()
  await manager.getByText(/День рождения/).first().waitFor()
  assert.equal(legacyPromptRequests, 0, 'Admin catalog must not trigger hidden legacy prompt reads')
  assert.deepEqual(errors,[])
  console.log('PASS: mobile categories, extensionless video, paginated repeat, admin edit/deactivate and audited history')
}finally{
  if(browser)await browser.close()
  server.kill('SIGTERM')
}
