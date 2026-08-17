import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as api from '../services/superAdminApi'
import type {
  CompanySubscriptionUpdate,
  CompanyUserCreate,
  PlatformCompanyCreate,
  PlatformCompanyProfileUpdate,
  PlatformCompanyUpdate,
  PlatformSettings,
  PlatformUserUpdate,
} from '../types/superAdmin'

export function usePlatformDashboard() {
  return useQuery({
    queryKey: ['super-admin', 'dashboard'],
    queryFn: () => api.fetchDashboard(),
  })
}

export function usePlatformCompanies(params?: { is_active?: boolean }) {
  return useQuery({
    queryKey: ['super-admin', 'companies', params],
    queryFn: () => api.listCompanies(params),
  })
}

export function usePlatformCompany(companyId: string | undefined) {
  return useQuery({
    queryKey: ['super-admin', 'companies', companyId],
    queryFn: () => api.getCompany(companyId!),
    enabled: Boolean(companyId),
  })
}

export function usePlatformCompanyMutations() {
  const qc = useQueryClient()
  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['super-admin', 'companies'] })
    void qc.invalidateQueries({ queryKey: ['super-admin', 'dashboard'] })
  }

  return {
    create: useMutation({
      mutationFn: (payload: PlatformCompanyCreate) => api.createCompany(payload),
      onSuccess: invalidate,
    }),
    update: useMutation({
      mutationFn: ({
        id,
        payload,
      }: {
        id: string
        payload: PlatformCompanyUpdate
      }) => api.updateCompany(id, payload),
      onSuccess: invalidate,
    }),
    updateProfile: useMutation({
      mutationFn: ({
        id,
        payload,
      }: {
        id: string
        payload: PlatformCompanyProfileUpdate
      }) => api.updateCompanyProfile(id, payload),
      onSuccess: (_data, vars) => {
        invalidate()
        void qc.invalidateQueries({
          queryKey: ['super-admin', 'companies', vars.id],
        })
      },
    }),
    activate: useMutation({
      mutationFn: (id: string) => api.activateCompany(id),
      onSuccess: invalidate,
    }),
    deactivate: useMutation({
      mutationFn: (id: string) => api.deactivateCompany(id),
      onSuccess: invalidate,
    }),
  }
}

export function useCompanySubscription(companyId: string | undefined) {
  return useQuery({
    queryKey: ['super-admin', 'companies', companyId, 'subscription'],
    queryFn: () => api.getCompanySubscription(companyId!),
    enabled: Boolean(companyId),
  })
}

export function useCompanySubscriptionMutations(companyId: string) {
  const qc = useQueryClient()
  const invalidate = () => {
    void qc.invalidateQueries({
      queryKey: ['super-admin', 'companies', companyId],
    })
    void qc.invalidateQueries({
      queryKey: ['super-admin', 'companies', companyId, 'subscription'],
    })
    void qc.invalidateQueries({
      queryKey: ['super-admin', 'companies', companyId, 'history'],
    })
  }

  return useMutation({
    mutationFn: (payload: CompanySubscriptionUpdate) =>
      api.updateCompanySubscription(companyId, payload),
    onSuccess: invalidate,
  })
}

export function useSubscriptionHistory(companyId: string | undefined) {
  return useQuery({
    queryKey: ['super-admin', 'companies', companyId, 'history'],
    queryFn: () => api.listSubscriptionHistory(companyId!),
    enabled: Boolean(companyId),
  })
}

export function useCompanyUsers(
  companyId: string | undefined,
  params?: { role?: string; status?: string },
) {
  return useQuery({
    queryKey: ['super-admin', 'companies', companyId, 'users', params],
    queryFn: () => api.listCompanyUsers(companyId!, params),
    enabled: Boolean(companyId),
  })
}

export function useCompanyUserMutations(companyId: string) {
  const qc = useQueryClient()
  const invalidate = () => {
    void qc.invalidateQueries({
      queryKey: ['super-admin', 'companies', companyId, 'users'],
    })
    void qc.invalidateQueries({ queryKey: ['super-admin', 'users'] })
  }

  return {
    create: useMutation({
      mutationFn: (payload: CompanyUserCreate) =>
        api.createCompanyUser(companyId, payload),
      onSuccess: invalidate,
    }),
    update: useMutation({
      mutationFn: ({
        id,
        payload,
      }: {
        id: string
        payload: PlatformUserUpdate
      }) => api.updateUser(id, payload),
      onSuccess: invalidate,
    }),
    block: useMutation({
      mutationFn: (id: string) => api.blockUser(id),
      onSuccess: invalidate,
    }),
    restore: useMutation({
      mutationFn: (id: string) => api.restoreUser(id),
      onSuccess: invalidate,
    }),
    resendInvite: useMutation({
      mutationFn: (id: string) => api.resendUserInvite(id),
    }),
  }
}

export function usePlatformUsers(params?: {
  company_id?: string
  role?: string
  status?: string
}) {
  return useQuery({
    queryKey: ['super-admin', 'users', params],
    queryFn: () => api.listUsers(params),
  })
}

export function usePlatformUserMutations() {
  const qc = useQueryClient()
  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['super-admin', 'users'] })
    void qc.invalidateQueries({ queryKey: ['super-admin', 'companies'] })
  }

  return {
    update: useMutation({
      mutationFn: ({
        id,
        payload,
      }: {
        id: string
        payload: PlatformUserUpdate
      }) => api.updateUser(id, payload),
      onSuccess: invalidate,
    }),
    block: useMutation({
      mutationFn: (id: string) => api.blockUser(id),
      onSuccess: invalidate,
    }),
    restore: useMutation({
      mutationFn: (id: string) => api.restoreUser(id),
      onSuccess: invalidate,
    }),
    resendInvite: useMutation({
      mutationFn: (id: string) => api.resendUserInvite(id),
    }),
  }
}

export function usePlatformAuditLogs(params?: { company_id?: string }) {
  return useQuery({
    queryKey: ['super-admin', 'audit-logs', params],
    queryFn: () => api.listAuditLogs(params),
  })
}

export function usePlatformSettings() {
  return useQuery({
    queryKey: ['super-admin', 'settings'],
    queryFn: () => api.fetchSettings(),
  })
}

export function usePlatformSettingsMutation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: Partial<PlatformSettings>) =>
      api.updateSettings(payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['super-admin', 'settings'] })
    },
  })
}
