'use client'

import { Component, type ErrorInfo, type ReactNode } from 'react'
import { AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface ClientErrorBoundaryProps {
  children: ReactNode
}

interface ClientErrorBoundaryState {
  hasError: boolean
}

export class ClientErrorBoundary extends Component<
  ClientErrorBoundaryProps,
  ClientErrorBoundaryState
> {
  state: ClientErrorBoundaryState = {
    hasError: false,
  }

  static getDerivedStateFromError(): ClientErrorBoundaryState {
    return { hasError: true }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Mini App client error', error, errorInfo)
  }

  render() {
    if (!this.state.hasError) {
      return this.props.children
    }

    return (
      <div className="flex min-h-screen items-center justify-center bg-background px-5 text-foreground">
        <div className="w-full max-w-sm rounded-2xl border border-border/60 bg-secondary/30 p-5 text-center">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-destructive/15">
            <AlertCircle className="h-6 w-6 text-destructive" />
          </div>
          <h1 className="mt-4 text-lg font-semibold">Не удалось открыть Mini App</h1>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            Обновите окно или откройте приложение заново из Telegram.
          </p>
          <Button
            className="mt-5 w-full bg-gold text-primary-foreground hover:bg-gold/90"
            onClick={() => window.location.reload()}
          >
            Обновить
          </Button>
        </div>
      </div>
    )
  }
}
