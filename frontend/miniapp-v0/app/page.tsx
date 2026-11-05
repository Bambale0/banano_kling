import { MiniAppShell } from '@/components/mini-app-shell'
import { TabContent } from '@/components/tab-content'
import { AccountPlatformEntry } from '@/components/account-platform-entry'

export default function Home() {
  return (
    <AccountPlatformEntry>
      <MiniAppShell>
        <TabContent />
      </MiniAppShell>
    </AccountPlatformEntry>
  )
}
