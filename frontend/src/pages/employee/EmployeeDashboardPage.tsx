import { Link } from 'react-router-dom'
import { PageHeader } from '../../components/common/PageHeader'
import { Button } from '../../components/ui/Button'
import { useAuth } from '../../hooks/useAuth'
import { useWorkspacePaths } from '../../hooks/useWorkspacePaths'
import { t } from '../../i18n'

/** Minimal employee web cabinet home — Telegram remains primary UX. */
export function EmployeeDashboardPage() {
  const { user } = useAuth()
  const paths = useWorkspacePaths()

  return (
    <div>
      <PageHeader
        title={t('employeeDashboard.title')}
        description={
          user?.company_name
            ? `${t('employeeDashboard.description')} · ${user.company_name}`
            : t('employeeDashboard.description')
        }
      />
      <div className="flex flex-wrap gap-3">
        <Link to={paths.path('/onboarding')}>
          <Button>{t('employeeDashboard.goOnboarding')}</Button>
        </Link>
        <Link to={paths.path('/active')}>
          <Button variant="secondary">{t('employeeDashboard.goActive')}</Button>
        </Link>
        <Link to={paths.path('/calendar')}>
          <Button variant="secondary">{t('employeeDashboard.goCalendar')}</Button>
        </Link>
      </div>
    </div>
  )
}
