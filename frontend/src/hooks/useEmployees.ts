import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as employeesApi from '../services/employeesApi'
import type {
  Employee,
  EmployeeCreate,
  EmployeeListParams,
  EmployeeUpdate,
} from '../types/employee'
import { useAuth } from './useAuth'

const LIST_LIMIT = 1000

export function useEmployees(
  filters: Omit<EmployeeListParams, 'company_id' | 'offset' | 'limit'> = {},
) {
  const { user } = useAuth()
  const companyId = user?.company_id

  return useQuery({
    queryKey: ['employees', companyId, filters],
    queryFn: () =>
      employeesApi.listEmployees({
        company_id: companyId!,
        status: filters.status,
        department_id: filters.department_id,
        offset: 0,
        limit: LIST_LIMIT,
      }),
    enabled: Boolean(companyId),
  })
}

export function useEmployee(employeeId: string | undefined) {
  return useQuery({
    queryKey: ['employee', employeeId],
    queryFn: () => employeesApi.getEmployee(employeeId!),
    enabled: Boolean(employeeId),
  })
}

export function useEmployeeInvites(employeeId: string | undefined) {
  return useQuery({
    queryKey: ['employee-invites', employeeId],
    queryFn: () => employeesApi.listInvites(employeeId!),
    enabled: Boolean(employeeId),
  })
}

export function useEmployeeMutations() {
  const qc = useQueryClient()
  const { user } = useAuth()

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['employees'] })
    void qc.invalidateQueries({ queryKey: ['employee'] })
    void qc.invalidateQueries({ queryKey: ['employee-invites'] })
  }

  const create = useMutation({
    mutationFn: (
      payload: Omit<EmployeeCreate, 'company_id'> & { company_id?: string },
    ) =>
      employeesApi.createEmployee({
        ...payload,
        company_id: payload.company_id ?? user!.company_id,
      }),
    onSuccess: invalidate,
  })

  const update = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: EmployeeUpdate }) =>
      employeesApi.updateEmployee(id, payload),
    onSuccess: (employee) => {
      qc.setQueryData(['employee', employee.id], employee)
      invalidate()
    },
  })

  const remove = useMutation({
    mutationFn: (id: string) => employeesApi.deleteEmployee(id),
    onMutate: async (id) => {
      await qc.cancelQueries({ queryKey: ['employees'] })
      const previous = qc.getQueriesData<Employee[]>({ queryKey: ['employees'] })
      qc.setQueriesData<Employee[]>({ queryKey: ['employees'] }, (old) =>
        old ? old.filter((e) => e.id !== id) : old,
      )
      qc.removeQueries({ queryKey: ['employee', id] })
      return { previous }
    },
    onError: (_err, _id, context) => {
      if (!context?.previous) return
      for (const [key, data] of context.previous) {
        qc.setQueryData(key, data)
      }
    },
    onSettled: invalidate,
  })

  return { create, update, remove }
}
