require "test_helper"

class Internal::LaminarControllerTest < ActionDispatch::IntegrationTest
  test "anonymous users are unauthorized" do
    get internal_laminar_authorize_url

    assert_response :unauthorized
  end

  test "active admins are authorized" do
    sign_in users(:acme_admin)

    get internal_laminar_authorize_url

    assert_response :no_content
  end

  test "pending users are forbidden" do
    sign_in users(:pending_user)

    get internal_laminar_authorize_url

    assert_response :forbidden
  end

  test "disabled users are forbidden" do
    sign_in users(:acme_admin)
    users(:acme_admin).update!(status: :disabled)

    get internal_laminar_authorize_url

    assert_response :forbidden
  end

  test "active non-admins are forbidden" do
    sign_in users(:member_user)

    get internal_laminar_authorize_url

    assert_response :forbidden
  end

  test "descoped admins are forbidden" do
    sign_in users(:acme_admin)
    post console_descope_url

    get internal_laminar_authorize_url

    assert_response :forbidden
  end

  private

  def sign_in(user)
    post login_url, params: { email: user.email, password: "password123456" }
    assert_response :redirect
  end
end
