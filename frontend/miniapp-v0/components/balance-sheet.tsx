'use client'

import type { ComponentType } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Banana, CreditCard, Gift, Receipt, Sparkles, X } from 'lucide-react'
import { useApp } from '@/lib/app-context'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'

export function BalanceSheet() {
  const { state, isBalanceOpen, closeBalance } = useApp()
  const { paymentPackages, user, recentTasks, mode } = state

  const totalSpent = recentTasks.reduce((sum, task) => sum + task.cost, 0)
  const imageTasks = recentTasks.filter((task) => task.type === 'image').length
  const videoTasks = recentTasks.filter((task) => task.type === 'video').length

  const handleTopup = async (packageId: string) => {
    const selectedPackage = paymentPackages.find((item) => item.id === packageId)
    if (!selectedPackage) return
    toast.success(`Пакет ${selectedPackage.name}`, {
      description: `Фронтовое пополнение готово: ${selectedPackage.credits}🍌 за ${selectedPackage.price_rub}₽. Следующий шаг — подключить платёжный confirm flow в этом sheet.`,
    })
  }

  return (
    <AnimatePresence>
      {isBalanceOpen && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={closeBalance}
            className="fixed inset-0 z-50 bg-background/80 backdrop-blur-sm"
          />

          <motion.div
            initial={{ opacity: 0, y: '100%' }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: '100%' }}
            transition={{ type: 'spring', damping: 28, stiffness: 280, mass: 0.8 }}
            className="fixed bottom-0 left-0 right-0 z-50 max-h-[88vh] overflow-auto rounded-t-3xl border-t border-border/50 glass-strong safe-bottom"
          >
            <div className="sticky top-0 z-10 bg-inherit px-5 pt-3 pb-3">
              <div className="mx-auto mb-3 h-1 w-10 rounded-full bg-border" />
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs uppercase tracking-[0.18em] text-gold/80">Баланс и пакеты</p>
                  <h2 className="font-serif text-xl font-semibold text-foreground">Пополнение баланса</h2>
                </div>
                <button
                  onClick={closeBalance}
                  className="flex h-8 w-8 items-center justify-center rounded-full bg-secondary/80 transition-colors hover:bg-secondary"
                >
                  <X className="h-4 w-4 text-muted-foreground" />
                </button>
              </div>
            </div>

            <div className="space-y-5 px-5 pb-6">
              <div className="rounded-2xl border border-gold/20 bg-gold/10 p-4">
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <p className="text-sm text-muted-foreground">Доступно сейчас</p>
                    <div className="mt-1 flex items-center gap-2">
                      <Banana className="h-5 w-5 text-gold" />
                      <span className="text-2xl font-semibold text-gold">{user.credits}</span>
                    </div>
                    <p className="mt-2 text-xs text-muted-foreground">Welcome-бонус для новых пользователей: 25🍌</p>
                  </div>
                  <div className="rounded-2xl border border-cyan/20 bg-background/30 px-4 py-3 text-right">
                    <p className="text-xs text-muted-foreground">Режим</p>
                    <p className="text-sm font-medium text-foreground">{mode === 'demo' ? 'Просмотр' : 'Онлайн'}</p>
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <StatCard icon={Sparkles} label="Всего запусков" value={`${recentTasks.length}`} />
                <StatCard icon={Receipt} label="Потрачено" value={`${totalSpent}🍌`} />
                <StatCard icon={Gift} label="Фото" value={`${imageTasks}`} />
                <StatCard icon={CreditCard} label="Видео" value={`${videoTasks}`} />
              </div>

              <div>
                <div className="mb-3 flex items-center justify-between">
                  <h3 className="font-serif text-lg text-foreground">Пакеты бананов</h3>
                  <span className="text-xs text-muted-foreground">Быстрый выбор пакета</span>
                </div>

                <div className="space-y-3">
                  {paymentPackages.map((pkg) => {
                    const pricePerBanana = Math.round(pkg.price_rub / pkg.credits)
                    return (
                      <div
                        key={pkg.id}
                        className={cn(
                          'rounded-2xl border p-4 transition-all duration-200',
                          pkg.popular
                            ? 'border-gold/40 bg-gold/10'
                            : 'border-border/50 bg-secondary/20'
                        )}
                      >
                        <div className="flex items-start justify-between gap-4">
                          <div>
                            <div className="flex items-center gap-2">
                              <h4 className="text-base font-semibold text-foreground">{pkg.name}</h4>
                              {pkg.popular && (
                                <span className="rounded-full border border-gold/30 bg-gold/15 px-2 py-0.5 text-[10px] font-medium text-gold">
                                  Popular
                                </span>
                              )}
                            </div>
                            <p className="mt-1 text-sm text-muted-foreground">{pkg.description}</p>
                            <p className="mt-2 text-xs text-muted-foreground">
                              {pkg.credits}🍌 • около {pricePerBanana}₽ за банан
                            </p>
                          </div>
                          <div className="text-right">
                            <p className="text-xl font-semibold text-foreground">{pkg.price_rub}₽</p>
                            <p className="text-xs text-muted-foreground">{pkg.credits} бананов</p>
                          </div>
                        </div>

                        <Button
                          onClick={() => handleTopup(pkg.id)}
                          className={cn(
                            'mt-4 w-full',
                            pkg.popular
                              ? 'bg-gold hover:bg-gold/90 text-primary-foreground'
                              : 'bg-secondary hover:bg-secondary/80 text-foreground'
                          )}
                        >
                          Выбрать пакет
                        </Button>
                      </div>
                    )
                  })}
                </div>
              </div>

              <div className="grid gap-3 md:grid-cols-2">
                <Button
                  onClick={() => toast.success('Статистика обновлена', { description: 'Карточки выше показывают расходы, баланс и активность по задачам.' })}
                  variant="outline"
                  className="border-border/50 bg-secondary/20 text-foreground hover:bg-secondary/40"
                >
                  Обновить статистику
                </Button>
                <Button onClick={() => handleTopup(paymentPackages[0]?.id || 'mini')} className="bg-gold hover:bg-gold/90 text-primary-foreground">
                  Продолжить пополнение
                </Button>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}

function StatCard({
  icon: Icon,
  label,
  value,
}: {
  icon: ComponentType<{ className?: string }>
  label: string
  value: string
}) {
  return (
    <div className="rounded-2xl border border-border/50 bg-secondary/20 p-4">
      <div className="mb-2 flex h-9 w-9 items-center justify-center rounded-xl bg-background/40">
        <Icon className="h-4 w-4 text-gold" />
      </div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-base font-semibold text-foreground">{value}</p>
    </div>
  )
}
