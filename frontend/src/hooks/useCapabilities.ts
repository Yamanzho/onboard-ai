import { useCallback } from 'react'
import { can, userCapabilities } from '../lib/capabilities'
import { useAuth } from './useAuth'

export function useCapabilities() {
  const { user } = useAuth()
  const canDo = useCallback(
    (capability: string) => can(user, capability),
    [user],
  )
  return {
    can: canDo,
    capabilities: userCapabilities(user),
    user,
  }
}
