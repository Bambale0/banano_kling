/**
 * Current Mini App smoke tests.
 *
 * These tests intentionally exercise stable public utilities and UI primitives.
 * Feature-specific flows live in their dedicated test files.
 */

import React from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import '@testing-library/jest-dom'

import { copyTextToClipboard } from '@/lib/clipboard'
import { mockAppState, mockTasks } from '@/lib/mock-data'
import { parseMiniAppStartParam } from '@/lib/start-params'
import { cn } from '@/lib/utils'

import { ModeBadge } from '@/components/mode-badge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Empty,
  EmptyDescription,
  EmptyTitle,
} from '@/components/ui/empty'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'

describe('Mini App smoke', () => {
  describe('start params', () => {
    it('parses current deep-link targets', () => {
      expect(parseMiniAppStartParam('feed_123_ref_ab12')).toEqual({
        kind: 'feed',
        genId: 123,
        referralCodeForAttribution: 'AB12',
      })
      expect(parseMiniAppStartParam('prompt_77')).toEqual({
        kind: 'prompt',
        promptId: 77,
        referralCodeForAttribution: '',
      })
      expect(parseMiniAppStartParam('task_abc-123')).toEqual({
        kind: 'task',
        taskId: 'abc-123',
      })
      expect(parseMiniAppStartParam('profile_demo')).toEqual({
        kind: 'profile',
        referralCode: 'DEMO',
        referralCodeForAttribution: 'DEMO',
      })
    })

    it('keeps plain referrals as attribution-only and rejects invalid targets', () => {
      expect(parseMiniAppStartParam('ref_demo')).toBeNull()
      expect(parseMiniAppStartParam('feed_0')).toBeNull()
      expect(parseMiniAppStartParam('unknown')).toBeNull()
      expect(parseMiniAppStartParam('')).toBeNull()
    })
  })

  describe('clipboard', () => {
    it('uses the Clipboard API when available', async () => {
      const writeText = jest.fn().mockResolvedValue(undefined)
      Object.defineProperty(navigator, 'clipboard', {
        configurable: true,
        value: { writeText },
      })

      await copyTextToClipboard(' https://example.test/demo ')

      expect(writeText).toHaveBeenCalledWith('https://example.test/demo')
    })
  })

  describe('mock fixtures', () => {
    it('contains valid current task fixtures', () => {
      expect(mockTasks.length).toBeGreaterThan(0)
      for (const task of mockTasks) {
        expect(task.task_id).toBeTruthy()
        expect(['image', 'video']).toContain(task.type)
        expect(['pending', 'completed', 'failed', 'processing']).toContain(task.status)
        expect(task.model).toBeTruthy()
      }
    })

    it('contains the current app-state shape', () => {
      expect(mockAppState.user.telegramId).toBeGreaterThan(0)
      expect(mockAppState.imageModels.length).toBeGreaterThan(0)
      expect(mockAppState.videoModels.length).toBeGreaterThan(0)
      expect(mockAppState.recentTasks).toBe(mockTasks)
    })
  })

  describe('UI primitives', () => {
    it('merges class names with Tailwind conflict resolution', () => {
      expect(cn('foo', 'bar')).toBe('foo bar')
      expect(cn('px-4', 'px-2')).toBe('px-2')
    })

    it('renders and clicks a button', () => {
      const onClick = jest.fn()
      render(<Button onClick={onClick}>Запустить</Button>)
      fireEvent.click(screen.getByRole('button', { name: 'Запустить' }))
      expect(onClick).toHaveBeenCalledTimes(1)
    })

    it('accepts text input', async () => {
      render(<Input aria-label="Промпт" />)
      const input = screen.getByRole('textbox', { name: 'Промпт' })
      await userEvent.type(input, 'hello')
      expect(input).toHaveValue('hello')
    })

    it('renders badge, spinner and skeleton', () => {
      const { container } = render(
        <div>
          <Badge>NEW</Badge>
          <Spinner data-testid="spinner" />
          <Skeleton data-testid="skeleton" className="h-10" />
        </div>,
      )
      expect(screen.getByText('NEW')).toBeInTheDocument()
      expect(screen.getByTestId('spinner')).toBeInTheDocument()
      expect(screen.getByTestId('skeleton')).toHaveClass('h-10')
      expect(container.firstChild).toBeInTheDocument()
    })

    it('renders current online/Telegram mode labels', () => {
      const { rerender } = render(<ModeBadge mode="live" />)
      expect(screen.getByText('Онлайн')).toBeInTheDocument()
      rerender(<ModeBadge mode="locked" />)
      expect(screen.getByText('Telegram')).toBeInTheDocument()
    })

    it('renders the current empty-state composition', () => {
      render(
        <Empty>
          <EmptyTitle>Пока пусто</EmptyTitle>
          <EmptyDescription>Создайте первую генерацию</EmptyDescription>
        </Empty>,
      )
      expect(screen.getByText('Пока пусто')).toBeInTheDocument()
      expect(screen.getByText('Создайте первую генерацию')).toBeInTheDocument()
    })
  })
})
