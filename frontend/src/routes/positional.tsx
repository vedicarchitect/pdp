import { createFileRoute } from '@tanstack/react-router'
import { PositionalPage } from '../components/positional/PositionalPage'

export const Route = createFileRoute('/positional')({
  component: PositionalPage,
})
