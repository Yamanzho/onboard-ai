import { useState, type FormEvent, type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  EmptyState,
  ErrorAlert,
  LoadingBlock,
  PageHeader,
} from '../../components/common/PageHeader'
import {
  EmployeeRoleBadge,
  EmployeeStatusBadge,
} from '../../components/employees/EmployeeBadges'
import { Badge } from '../../components/ui/Badge'
import { Button } from '../../components/ui/Button'
import { Input, Label, Select } from '../../components/ui/Field'
import {
  useCompanySubscriptionMutations,
  useCompanyUserMutations,
  useCompanyUsers,
  usePlatformCompany,
  usePlatformCompanyMutations,
  useSubscriptionHistory,
} from '../../hooks/useSuperAdmin'
import { usePlatformPaths } from '../../hooks/useWorkspacePaths'
import {
  labelCompanyActive,
  labelEmployeeRole,
  labelPaymentStatus,
  labelSubscriptionStatus,
  labelSubscriptionTier,
  t,
} from '../../i18n'
import { ApiError } from '../../services/apiClient'
import type {
  PlatformCompanyDetail,
  PlatformUser,
  SubscriptionStatus,
  SubscriptionTier,
} from '../../types/superAdmin'

type Tab = 'profile' | 'subscription' | 'users' | 'history' | 'limits'

const tabs: { id: Tab; labelKey: string }[] = [
  { id: 'profile', labelKey: 'superAdmin.companies.detail.tabProfile' },
  { id: 'subscription', labelKey: 'superAdmin.companies.detail.tabSubscription' },
  { id: 'limits', labelKey: 'superAdmin.companies.detail.tabLimits' },
  { id: 'users', labelKey: 'superAdmin.companies.detail.tabUsers' },
  { id: 'history', labelKey: 'superAdmin.companies.detail.tabHistory' },
]

const SUBSCRIPTION_TIERS = ['starter', 'professional', 'enterprise'] as const
const SUBSCRIPTION_STATUSES = [
  'trial',
  'active',
  'suspended',
  'expired',
  'blocked',
] as const
const PAYMENT_STATUSES = ['unpaid', 'paid', 'past_due'] as const
const USER_ROLES = ['admin', 'hr', 'employee'] as const

export function SuperAdminCompanyDetailPage() {
  const { companyId } = useParams<{ companyId: string }>()
  const paths = usePlatformPaths()
  const [tab, setTab] = useState<Tab>('profile')
  const { data, isLoading, error } = usePlatformCompany(companyId)
  const { activate, deactivate } = usePlatformCompanyMutations()
  const [actionError, setActionError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function toggleActive() {
    if (!data) return
    setActionError(null)
    setBusy(true)
    try {
      if (data.is_active) {
        await deactivate.mutateAsync(data.id)
      } else {
        await activate.mutateAsync(data.id)
      }
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : t('common.actionFailed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <PageHeader
        title={data?.name ?? t('superAdmin.companies.detail.fallbackTitle')}
        description={
          data
            ? t('superAdmin.companies.detail.slugDescription', { slug: data.slug })
            : undefined
        }
        action={
          <div className="flex flex-wrap gap-2">
            <Link to={paths.companies}>
              <Button variant="secondary">{t('common.back')}</Button>
            </Link>
            {data ? (
              <>
                <Link to={paths.companyEdit(data.id)}>
                  <Button variant="secondary">{t('common.edit')}</Button>
                </Link>
                <Button
                  variant={data.is_active ? 'danger' : 'primary'}
                  disabled={busy}
                  onClick={() => void toggleActive()}
                >
                  {data.is_active ? t('common.block') : t('common.activate')}
                </Button>
              </>
            ) : null}
          </div>
        }
      />

      {actionError ? <ErrorAlert message={actionError} /> : null}
      {error instanceof Error ? <ErrorAlert message={error.message} /> : null}

      {isLoading || !data ? (
        <LoadingBlock label={t('superAdmin.companies.detail.loading')} />
      ) : (
        <>
          <div className="mb-4 flex flex-wrap gap-2 border-b border-[var(--color-border)]">
            {tabs.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => setTab(item.id)}
                className={`border-b-2 px-3 py-2 text-sm transition ${
                  tab === item.id
                    ? 'border-[var(--color-accent)] font-medium text-[var(--color-accent)]'
                    : 'border-transparent text-[var(--color-muted)] hover:text-[var(--color-text)]'
                }`}
              >
                {t(item.labelKey)}
              </button>
            ))}
          </div>

          {tab === 'profile' ? <ProfileTab company={data} /> : null}
          {tab === 'subscription' ? (
            <SubscriptionTab company={data} />
          ) : null}
          {tab === 'limits' ? <LimitsTab company={data} /> : null}
          {tab === 'users' ? <UsersTab companyId={data.id} /> : null}
          {tab === 'history' ? <HistoryTab companyId={data.id} /> : null}
        </>
      )}
    </div>
  )
}

function ProfileTab({ company }: { company: PlatformCompanyDetail }) {
  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-[var(--color-border)] bg-white p-6">
        <div className="mb-4 flex items-start gap-4">
          {company.logo_url ? (
            <img
              src={company.logo_url}
              alt={t('superAdmin.companies.detail.logoAlt', { name: company.name })}
              className="h-16 w-16 rounded-lg border border-[var(--color-border)] object-cover"
            />
          ) : (
            <div className="flex h-16 w-16 items-center justify-center rounded-lg border border-dashed border-[var(--color-border)] text-xs text-[var(--color-muted)]">
              {t('superAdmin.companies.detail.noLogo')}
            </div>
          )}
          <div>
            <h2 className="text-lg font-semibold">{company.name}</h2>
            <p className="text-sm text-[var(--color-muted)]">{company.slug}</p>
            <div className="mt-2">
              <Badge tone={company.is_active ? 'success' : 'danger'}>
                {labelCompanyActive(company.is_active)}
              </Badge>
            </div>
          </div>
        </div>
        {company.description ? (
          <p className="mb-4 text-sm text-[var(--color-muted)]">
            {company.description}
          </p>
        ) : null}
        <dl className="grid gap-4 sm:grid-cols-2">
          <Item
            label={t('superAdmin.companies.detail.registered')}
            value={formatDate(company.created_at)}
          />
          <Item label={t('common.timezone')} value={company.timezone} />
          <Item
            label={t('superAdmin.companies.detail.contactPerson')}
            value={company.contact_person ?? t('common.emDash')}
          />
          <Item
            label={t('superAdmin.companies.detail.contactEmail')}
            value={company.contact_email ?? t('common.emDash')}
          />
          <Item
            label={t('superAdmin.companies.detail.contactPhone')}
            value={company.contact_phone ?? t('common.emDash')}
          />
          <Item
            label={t('superAdmin.companies.detail.companyId')}
            value={company.id}
          />
        </dl>
      </div>
      <div className="grid gap-4 sm:grid-cols-3">
        <Stat label={t('superAdmin.dashboard.employees')} value={company.employees_count} />
        <Stat label={t('nav.onboarding')} value={company.programs_count} />
        <Stat label={t('nav.assignments')} value={company.assignments_count} />
      </div>
    </div>
  )
}

function SubscriptionTab({ company }: { company: PlatformCompanyDetail }) {
  const sub = company.subscription
  const updateSub = useCompanySubscriptionMutations(company.id)
  const [error, setError] = useState<string | null>(null)
  const [tier, setTier] = useState(sub?.tier ?? 'starter')
  const [status, setStatus] = useState(sub?.status ?? 'trial')
  const [paymentStatus, setPaymentStatus] = useState(sub?.payment_status ?? 'unpaid')
  const [autoRenew, setAutoRenew] = useState(sub?.auto_renew ?? true)

  if (!sub) {
    return (
      <EmptyState
        title={t('superAdmin.companies.detail.noSubscription')}
        description={t('superAdmin.companies.detail.noSubscriptionHint')}
      />
    )
  }

  async function onSave(e: FormEvent) {
    e.preventDefault()
    setError(null)
    try {
      await updateSub.mutateAsync({
        tier: tier as SubscriptionTier,
        status: status as SubscriptionStatus,
        payment_status: paymentStatus as 'unpaid' | 'paid' | 'past_due',
        auto_renew: autoRenew,
      })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('common.updateFailed'))
    }
  }

  return (
    <div className="space-y-4">
      {error ? <ErrorAlert message={error} /> : null}
      <div className="rounded-lg border border-[var(--color-border)] bg-white p-6">
        <h3 className="mb-4 text-sm font-semibold">
          {t('superAdmin.companies.detail.currentSubscription')}
        </h3>
        <dl className="grid gap-4 sm:grid-cols-2">
          <Item label={t('superAdmin.companies.detail.tier')} value={labelSubscriptionTier(sub.tier)} />
          <Item
            label={t('common.status')}
            value={<StatusBadge status={sub.status} />}
          />
          <Item
            label={t('superAdmin.companies.detail.payment')}
            value={labelPaymentStatus(sub.payment_status)}
          />
          <Item
            label={t('superAdmin.companies.detail.started')}
            value={formatDate(sub.started_at)}
          />
          <Item
            label={t('superAdmin.companies.detail.ends')}
            value={sub.ends_at ? formatDate(sub.ends_at) : t('common.emDash')}
          />
          <Item
            label={t('superAdmin.companies.detail.autoRenew')}
            value={sub.auto_renew ? t('common.yes') : t('common.no')}
          />
        </dl>
      </div>

      <form
        onSubmit={onSave}
        className="max-w-xl space-y-3 rounded-lg border border-[var(--color-border)] bg-white p-6"
      >
        <h3 className="text-sm font-semibold">
          {t('superAdmin.companies.detail.updateSubscription')}
        </h3>
        <div>
          <Label htmlFor="tier">{t('superAdmin.companies.detail.tier')}</Label>
          <Select id="tier" value={tier} onChange={(e) => setTier(e.target.value)}>
            {SUBSCRIPTION_TIERS.map((value) => (
              <option key={value} value={value}>
                {labelSubscriptionTier(value)}
              </option>
            ))}
          </Select>
        </div>
        <div>
          <Label htmlFor="status">{t('common.status')}</Label>
          <Select
            id="status"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          >
            {SUBSCRIPTION_STATUSES.map((value) => (
              <option key={value} value={value}>
                {labelSubscriptionStatus(value)}
              </option>
            ))}
          </Select>
        </div>
        <div>
          <Label htmlFor="payment">
            {t('superAdmin.companies.detail.paymentStatus')}
          </Label>
          <Select
            id="payment"
            value={paymentStatus}
            onChange={(e) => setPaymentStatus(e.target.value)}
          >
            {PAYMENT_STATUSES.map((value) => (
              <option key={value} value={value}>
                {labelPaymentStatus(value)}
              </option>
            ))}
          </Select>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={autoRenew}
            onChange={(e) => setAutoRenew(e.target.checked)}
          />
          {t('superAdmin.companies.detail.autoRenew')}
        </label>
        <Button type="submit" disabled={updateSub.isPending}>
          {updateSub.isPending
            ? t('common.saving')
            : t('superAdmin.companies.detail.saveSubscription')}
        </Button>
      </form>
    </div>
  )
}

function LimitsTab({ company }: { company: PlatformCompanyDetail }) {
  const limits = company.limits
  if (!limits) {
    return <LoadingBlock label={t('superAdmin.companies.detail.loadingLimits')} />
  }

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <LimitCard
        label={t('superAdmin.dashboard.employees')}
        used={limits.employees_used}
        limit={limits.employee_limit}
      />
      <LimitCard
        label={t('nav.onboarding')}
        used={limits.programs_used}
        limit={limits.program_limit}
      />
    </div>
  )
}

function UsersTab({ companyId }: { companyId: string }) {
  const { data, isLoading, error } = useCompanyUsers(companyId)
  const { create, block, restore, resendInvite } = useCompanyUserMutations(companyId)
  const [actionError, setActionError] = useState<string | null>(null)
  const [actionSuccess, setActionSuccess] = useState<string | null>(null)
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [role, setRole] = useState('admin')
  const [busyId, setBusyId] = useState<string | null>(null)

  async function onCreate(e: FormEvent) {
    e.preventDefault()
    setActionError(null)
    setActionSuccess(null)
    try {
      const created = await create.mutateAsync({
        full_name: fullName.trim(),
        email: email.trim(),
        role: role as 'admin' | 'hr' | 'employee',
      })
      setFullName('')
      setEmail('')
      if (created.invite_delivery === 'email') {
        setActionError(
          t('superAdmin.companies.detail.inviteEmailSent', {
            email: created.email ?? email.trim(),
          }),
        )
      } else if (created.invite_delivery === 'manual_url' && created.invite_url) {
        const smtpOff = (created.invite_detail ?? '')
          .toLowerCase()
          .includes('not configured')
        setActionError(
          t(
            smtpOff
              ? 'superAdmin.companies.detail.inviteManualUrl'
              : 'superAdmin.companies.detail.inviteSendFailed',
            { url: created.invite_url },
          ),
        )
      }
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : t('common.createFailed'))
    }
  }

  async function onBlock(user: PlatformUser) {
    const ok = window.confirm(
      t('superAdmin.companies.detail.blockConfirm', { name: user.full_name }),
    )
    if (!ok) return
    setActionError(null)
    setActionSuccess(null)
    setBusyId(user.id)
    try {
      await block.mutateAsync(user.id)
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : t('common.actionFailed'))
    } finally {
      setBusyId(null)
    }
  }

  async function onRestore(user: PlatformUser) {
    const ok = window.confirm(
      t('superAdmin.companies.detail.restoreConfirm', { name: user.full_name }),
    )
    if (!ok) return
    setActionError(null)
    setActionSuccess(null)
    setBusyId(user.id)
    try {
      await restore.mutateAsync(user.id)
      setActionSuccess(
        t('superAdmin.companies.detail.restoreSuccess', { name: user.full_name }),
      )
    } catch (err) {
      setActionError(
        err instanceof ApiError
          ? err.message
          : t('superAdmin.companies.detail.restoreFailed'),
      )
    } finally {
      setBusyId(null)
    }
  }

  async function onResend(user: PlatformUser) {
    setBusyId(user.id)
    setActionError(null)
    setActionSuccess(null)
    try {
      const delivery = await resendInvite.mutateAsync(user.id)
      if (delivery.delivery === 'email') {
        setActionError(
          t('superAdmin.companies.detail.inviteEmailSent', {
            email: user.email ?? '',
          }),
        )
      } else if (delivery.delivery === 'manual_url' && delivery.invite_url) {
        const smtpOff = (delivery.detail ?? '')
          .toLowerCase()
          .includes('not configured')
        setActionError(
          t(
            smtpOff
              ? 'superAdmin.companies.detail.inviteManualUrl'
              : 'superAdmin.companies.detail.inviteSendFailed',
            { url: delivery.invite_url },
          ),
        )
      }
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : t('superAdmin.companies.detail.resendFailed'),
      )
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="space-y-4">
      {actionError ? <ErrorAlert message={actionError} /> : null}
      {actionSuccess ? (
        <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          {actionSuccess}
        </div>
      ) : null}
      {error instanceof Error ? <ErrorAlert message={error.message} /> : null}

      <form
        onSubmit={onCreate}
        className="grid gap-3 rounded-lg border border-[var(--color-border)] bg-white p-4 md:grid-cols-4"
      >
        <Input
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
          placeholder={t('superAdmin.companies.detail.fullNamePlaceholder')}
          required
        />
        <Input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder={t('superAdmin.companies.detail.emailPlaceholder')}
          required
        />
        <Select value={role} onChange={(e) => setRole(e.target.value)}>
          {USER_ROLES.map((value) => (
            <option key={value} value={value}>
              {labelEmployeeRole(value)}
            </option>
          ))}
        </Select>
        <Button type="submit" disabled={create.isPending}>
          {create.isPending
            ? t('superAdmin.companies.detail.sendingInvite')
            : t('superAdmin.companies.detail.inviteUser')}
        </Button>
      </form>

      {isLoading ? (
        <LoadingBlock label={t('superAdmin.users.loading')} />
      ) : (data ?? []).length === 0 ? (
        <EmptyState
          title={t('superAdmin.companies.detail.noUsers')}
          description={t('superAdmin.companies.detail.noUsersHint')}
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-[var(--color-border)] bg-white">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-[var(--color-muted)]">
              <tr>
                <th className="px-4 py-3">{t('common.name')}</th>
                <th className="px-4 py-3">{t('common.email')}</th>
                <th className="px-4 py-3">{t('common.role')}</th>
                <th className="px-4 py-3">{t('common.status')}</th>
                <th className="px-4 py-3">
                  {t('superAdmin.companies.detail.lastLogin')}
                </th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-border)]">
              {(data ?? []).map((user) => (
                <tr key={user.id}>
                  <td className="px-4 py-3 font-medium">{user.full_name}</td>
                  <td className="px-4 py-3">{user.email ?? t('common.emDash')}</td>
                  <td className="px-4 py-3">
                    <EmployeeRoleBadge role={user.role} />
                  </td>
                  <td className="px-4 py-3">
                    <EmployeeStatusBadge status={user.status} />
                  </td>
                  <td className="px-4 py-3 text-[var(--color-muted)]">
                    {user.last_login_at
                      ? formatDate(user.last_login_at)
                      : t('common.emDash')}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex justify-end gap-2">
                      {user.status === 'invited' ? (
                        <Button
                          variant="secondary"
                          disabled={busyId === user.id}
                          onClick={() => void onResend(user)}
                        >
                          {t('superAdmin.companies.detail.resendInvite')}
                        </Button>
                      ) : null}
                      {user.status === 'archived' ? (
                        <Button
                          variant="secondary"
                          disabled={busyId === user.id}
                          onClick={() => void onRestore(user)}
                        >
                          {t('common.restore')}
                        </Button>
                      ) : (
                        <Button
                          variant="danger"
                          disabled={busyId === user.id}
                          onClick={() => void onBlock(user)}
                        >
                          {t('common.block')}
                        </Button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function HistoryTab({ companyId }: { companyId: string }) {
  const { data, isLoading, error } = useSubscriptionHistory(companyId)

  if (isLoading) return <LoadingBlock label={t('common.loading')} />
  if (error instanceof Error) return <ErrorAlert message={error.message} />
  if ((data ?? []).length === 0) {
    return (
      <EmptyState
        title={t('superAdmin.companies.detail.noHistory')}
        description={t('superAdmin.companies.detail.noHistoryHint')}
      />
    )
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-[var(--color-border)] bg-white">
      <table className="min-w-full text-left text-sm">
        <thead className="bg-slate-50 text-xs uppercase text-[var(--color-muted)]">
          <tr>
            <th className="px-4 py-3">{t('superAdmin.companies.detail.colWhen')}</th>
            <th className="px-4 py-3">{t('superAdmin.companies.detail.colEvent')}</th>
            <th className="px-4 py-3">{t('common.status')}</th>
            <th className="px-4 py-3">{t('superAdmin.companies.detail.colTier')}</th>
            <th className="px-4 py-3">{t('superAdmin.companies.detail.colNote')}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[var(--color-border)]">
          {(data ?? []).map((event) => (
            <tr key={event.id}>
              <td className="px-4 py-3 text-[var(--color-muted)]">
                {formatDate(event.created_at)}
              </td>
              <td className="px-4 py-3">{event.event_type}</td>
              <td className="px-4 py-3">
                {event.previous_status
                  ? `${labelSubscriptionStatus(event.previous_status)} → ${event.new_status ? labelSubscriptionStatus(event.new_status) : t('common.emDash')}`
                  : (event.new_status
                      ? labelSubscriptionStatus(event.new_status)
                      : t('common.emDash'))}
              </td>
              <td className="px-4 py-3">
                {event.previous_tier
                  ? `${labelSubscriptionTier(event.previous_tier)} → ${event.new_tier ? labelSubscriptionTier(event.new_tier) : t('common.emDash')}`
                  : (event.new_tier
                      ? labelSubscriptionTier(event.new_tier)
                      : t('common.emDash'))}
              </td>
              <td className="px-4 py-3 text-[var(--color-muted)]">
                {event.note ?? t('common.emDash')}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Item({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-[var(--color-muted)]">
        {label}
      </dt>
      <dd className="mt-1 text-sm">{value}</dd>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-white px-4 py-4">
      <p className="text-xs uppercase tracking-wide text-[var(--color-muted)]">
        {label}
      </p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
    </div>
  )
}

function LimitCard({
  label,
  used,
  limit,
}: {
  label: string
  used: number
  limit: number
}) {
  const pct = limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0
  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-white p-6">
      <p className="text-xs uppercase tracking-wide text-[var(--color-muted)]">
        {label}
      </p>
      <p className="mt-1 text-2xl font-semibold">
        {used} / {limit}
      </p>
      <div className="mt-3 h-2 rounded-full bg-slate-100">
        <div
          className="h-2 rounded-full bg-[var(--color-accent)]"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const tone =
    status === 'active' || status === 'trial'
      ? 'success'
      : status === 'suspended'
        ? 'warning'
        : 'danger'
  return <Badge tone={tone}>{labelSubscriptionStatus(status)}</Badge>
}

function formatDate(value: string) {
  return new Date(value).toLocaleString()
}
