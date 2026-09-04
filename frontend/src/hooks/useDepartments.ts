import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as departmentsApi from '../services/departmentsApi'
import type { DepartmentCreate, DepartmentUpdate } from '../types/department'
import { useAuth } from './useAuth'

export function useDepartments(isActive?: boolean) {
  const { user } = useAuth()
  const companyId = user?.company_id

  return useQuery({
    queryKey: ['departments', companyId, isActive],
    queryFn: () => departmentsApi.listDepartments(companyId!, isActive),
    enabled: Boolean(companyId),
  })
}

export function useDepartmentMutations() {
  const qc = useQueryClient()
  const { user } = useAuth()

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['departments'] })
    void qc.invalidateQueries({ queryKey: ['employees'] })
    void qc.invalidateQueries({ queryKey: ['employee'] })
    void qc.invalidateQueries({ queryKey: ['topics'] })
  }

  const create = useMutation({
    mutationFn: (
      payload: Omit<DepartmentCreate, 'company_id'> & { company_id?: string },
    ) =>
      departmentsApi.createDepartment({
        ...payload,
        company_id: payload.company_id ?? user!.company_id,
      }),
    onSuccess: invalidate,
  })

  const update = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: DepartmentUpdate }) =>
      departmentsApi.updateDepartment(id, payload),
    onSuccess: invalidate,
  })

  return { create, update }
}
