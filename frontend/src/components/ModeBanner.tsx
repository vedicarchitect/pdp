import { useTradeMode } from '../hooks/useTradeMode'
import { Badge } from './ui/Badge'
import { Tooltip } from './ui/Tooltip'

export default function ModeBanner({ collapsed = false }: { collapsed?: boolean }) {
  const mode = useTradeMode()

  if (collapsed) {
    if (mode === 'live') {
      return (
        <Tooltip content="Live Mode — Real money" placement="right">
          <Badge variant="danger" size="sm" className="rounded-md px-1.5 py-1 font-bold">L</Badge>
        </Tooltip>
      )
    }
    return (
      <Tooltip content="Paper Mode" placement="right">
        <Badge variant="warning" size="sm" className="rounded-md px-1.5 py-1 text-black font-bold">P</Badge>
      </Tooltip>
    )
  }

  if (mode === 'live') {
    return (
      <Badge variant="danger" className="w-full flex justify-center py-1.5 rounded-md font-bold tracking-widest uppercase">
        Live Mode
      </Badge>
    )
  }

  return (
    <Badge variant="warning" className="w-full flex justify-center py-1.5 rounded-md text-black font-bold tracking-widest uppercase">
      Paper Mode
    </Badge>
  )
}
