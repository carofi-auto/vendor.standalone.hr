import json
import re

import requests
from bs4 import BeautifulSoup
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from horilla.config import logger
from horilla.decorators import login_required, permission_required
from horilla.http.response import HorillaRedirect
from recruitment.models import LinkedInAccount


@login_required
@permission_required("recruitment.update_linkedinaccount")
def update_isactive_linkedin(request, obj_id):
    """
    htmx function to update is active field in LinkedInAccount.
    Args:
    - is_active: Boolean value representing the state of LinkedInAccount,
    - obj_id: Id of LinkedInAccount object.
    """
    linkedin_account = LinkedInAccount.find(obj_id)
    if not linkedin_account:
        return HorillaRedirect(
            request, message=_("No LinkedIn Account found matching the query.")
        )

    is_active = request.POST.get("is_active")
    if is_active == "on":
        linkedin_account.is_active = True
        messages.success(request, _("LinkedIn Account activated successfully."))
    else:
        linkedin_account.is_active = False
        messages.success(request, _("LinkedIn Account deactivated successfully."))
    linkedin_account.save()

    return HttpResponse("<script>$('#reloadMessagesButton').click();</script>")


@login_required
@permission_required("recruitment.delete_linkedinaccount")
def delete_linkedin_account(request, pk, return_redirect=True):
    """
    Delete Linkedin account
    """
    try:
        if return_redirect:
            LinkedInAccount.objects.get(id=pk).delete()
            messages.success(request, _("LinkedIn data deleted"))
            return redirect(reverse("linkedin-setting-list"))
    except Exception as e:
        logger.error(e)
        messages.error(request, _("Something went wrong"))
    return HorillaRedirect(request)


@login_required
def validate_linkedin_token(request, pk):
    linkedin_account = LinkedInAccount.find(pk)
    if not linkedin_account:
        return HorillaRedirect(
            request, message=_("No LinkedIn Account found matching the query.")
        )

    access_token = linkedin_account.api_token
    url = "https://api.linkedin.com/v2/userinfo"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url, headers=headers, timeout=30)
    if response.status_code == 200:
        messages.success(request, _("LinkedIn connection success."))
    else:
        messages.success(request, _("LinkedIn connection failed."))
    return HttpResponse("<script>$('#reloadMessagesButton').click();</script>")


def html_to_text(html):
    soup = BeautifulSoup(html, "html.parser")
    return "\n".join(
        p.get_text(strip=True)
        for p in soup.find_all(["p", "br"])
        if p.get_text(strip=True)
    )


def post_recruitment_in_linkedin(
    request, recruitment, linkedin_acc, feed_type="feed", group_id=None
):
    site_url = request.build_absolute_uri("/")[:-1]  # Gets the base URL
    recruitment_url = (
        f"{site_url}/recruitment/application-form?recruitmentId={recruitment.id}"
    )

    if not linkedin_acc.organization_id:
        logger.error(
            "LinkedIn account %s has no organization_id set; refusing to "
            "post to a personal feed.",
            linkedin_acc.id,
        )
        recruitment.publish_in_linkedin = False
        recruitment.save()
        return

    payload_dict = {
        "author": f"urn:li:organization:{linkedin_acc.organization_id}",
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": html_to_text(recruitment.description)},
                "shareMediaCategory": "ARTICLE",
                "media": [
                    {
                        "status": "READY",
                        "description": {"text": recruitment.description},
                        "originalUrl": recruitment_url,
                        "title": {"text": recruitment.title},
                        "thumbnails": [{"url": recruitment_url}],
                    }
                ],
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": (
                "PUBLIC" if feed_type == "feed" else "CONTAINER"
            )
        },
    }

    if feed_type == "group" and group_id:
        payload_dict["containerEntity"] = f"urn:li:group:{group_id}"

    url = "https://api.linkedin.com/v2/ugcPosts"
    payload = json.dumps(payload_dict)
    headers = {
        "Authorization": f"Bearer {linkedin_acc.api_token}",
        "Content-Type": "application/json",
    }
    response = requests.post(url, headers=headers, data=payload, timeout=30)
    if response.status_code == 201:
        response_data = response.json()
        post_id = response_data.get("id")
        logger.info(
            "LinkedIn ugcPosts succeeded: post_id=%s author=%s",
            post_id,
            payload_dict["author"],
        )
        recruitment.linkedin_post_id = post_id
        recruitment.save()
        return

    duplicate_urn = _extract_duplicate_post_urn(response)
    if duplicate_urn:
        logger.info(
            "LinkedIn ugcPosts duplicate detected; treating as success: post_id=%s",
            duplicate_urn,
        )
        recruitment.linkedin_post_id = duplicate_urn
        recruitment.save()
        return

    logger.error(
        "LinkedIn ugcPosts failed: status=%s body=%s author=%s",
        response.status_code,
        response.text,
        payload_dict["author"],
    )
    recruitment.publish_in_linkedin = False
    recruitment.save()


_DUPLICATE_URN_RE = re.compile(r"urn:li:share:\d+")


def _extract_duplicate_post_urn(response):
    """If LinkedIn rejected the post as a duplicate, return the existing URN."""
    if response.status_code != 422:
        return None
    try:
        body = response.json()
    except ValueError:
        return None

    is_duplicate = any(
        err.get("code") == "DUPLICATE_POST"
        for err in body.get("errorDetails", {}).get("inputErrors", [])
    )
    if not is_duplicate:
        return None

    match = _DUPLICATE_URN_RE.search(body.get("message", ""))
    return match.group(0) if match else None


def delete_post(recruitment):
    """Delete recruitment post from LinkedIn"""
    linkedin_post_id = recruitment.linkedin_post_id
    if not linkedin_post_id:
        return True  # 787

    url = f"https://api.linkedin.com/v2/ugcPosts/{linkedin_post_id}"
    headers = {
        "Authorization": f"Bearer {recruitment.linkedin_account_id.api_token}",
        "Content-Type": "application/json",
    }

    response = requests.delete(url, headers=headers, timeout=30)
    if response.status_code == 204:
        recruitment.linkedin_post_id = None
        recruitment.save()
        return True

    return False
