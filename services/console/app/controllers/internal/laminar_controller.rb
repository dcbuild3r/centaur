module Internal
  # Small, side-effect-free authorization endpoint for the private Laminar
  # gateway. It deliberately skips the normal Console page callbacks: Nginx's
  # auth_request needs a status-only response and must not initialize the
  # Console sidebar or redirect through the HTML login flow.
  class LaminarController < ApplicationController
    skip_before_action :require_login
    skip_before_action :require_active_account
    skip_before_action :init_console_sidebar_threads

    def authorize
      return head :unauthorized unless current_user
      return head :forbidden unless current_user.active? && acting_admin?

      head :no_content
    end
  end
end
