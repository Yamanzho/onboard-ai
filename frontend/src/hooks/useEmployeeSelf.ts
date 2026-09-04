import { useQuery } from '@tanstack/react-query'
import * as assignmentsApi from '../services/assignmentsApi'
import type { Assignment } from '../types/assignment'
import { compareAssignmentsByPriorityDeadline } from '../lib/progressUtils'

export function useEmployeeAssignments(
  employeeId: string | undefined,
  options: { status?: string; activeOnly?: boolean } = {},
) {
  return useQuery({
    queryKey: ['my-assignments', employeeId, options.status, options.activeOnly],
    queryFn: async (): Promise<Assignment[]> => {
      if (options.activeOnly) {
        const [pending, inProgress] = await Promise.all([
          assignmentsApi.listEmployeeAssignments(employeeId!, {
            status: 'pending',
          }),
          assignmentsApi.listEmployeeAssignments(employeeId!, {
            status: 'in_progress',
          }),
        ])
        return [...inProgress, ...pending].sort(compareAssignmentsByPriorityDeadline)
      }
      const items = await assignmentsApi.listEmployeeAssignments(employeeId!, {
        status: options.status,
      })
      if (options.status === 'pending' || options.status === 'in_progress') {
        return [...items].sort(compareAssignmentsByPriorityDeadline)
      }
      return items
    },
    enabled: Boolean(employeeId),
  })
}
