import os
import json
import logging
import requests
import dataclasses

from typing import List

DEBUG = os.environ.get("DEBUG", "false")
if DEBUG.lower() == "true":
    logging.basicConfig(level=logging.DEBUG)

AZURE_SEARCH_PERMITTED_GROUPS_COLUMN = os.environ.get(
    "AZURE_SEARCH_PERMITTED_GROUPS_COLUMN"
)


class JSONEncoder(json.JSONEncoder):
    def default(self, o):
        if dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)
        return super().default(o)


async def format_as_ndjson(r):
    try:
        async for event in r:
            yield json.dumps(event, cls=JSONEncoder) + "\n"
    except Exception as error:
        logging.exception("Exception while generating response stream: %s", error)
        yield json.dumps({"error": str(error)})


def parse_multi_columns(columns: str) -> list:
    if "|" in columns:
        return columns.split("|")
    else:
        return columns.split(",")


def fetchUserGroups(userToken, nextLink=None):
    # Recursively fetch group membership
    if nextLink:
        endpoint = nextLink
    else:
        endpoint = "https://graph.microsoft.com/v1.0/me/transitiveMemberOf?$select=id"

    headers = {"Authorization": "bearer " + userToken}
    try:
        r = requests.get(endpoint, headers=headers)
        if r.status_code != 200:
            logging.error(f"Error fetching user groups: {r.status_code} {r.text}")
            return []

        r = r.json()
        if "@odata.nextLink" in r:
            nextLinkData = fetchUserGroups(userToken, r["@odata.nextLink"])
            r["value"].extend(nextLinkData)

        return r["value"]
    except Exception as e:
        logging.error(f"Exception in fetchUserGroups: {e}")
        return []


def generateFilterString(userToken):
    # Get list of groups user is a member of
    userGroups = fetchUserGroups(userToken)

    # Construct filter string
    if not userGroups:
        logging.debug("No user groups found")

    group_ids = ", ".join([obj["id"] for obj in userGroups])
    return f"{AZURE_SEARCH_PERMITTED_GROUPS_COLUMN}/any(g:search.in(g, '{group_ids}'))"


def format_non_streaming_response(chatCompletion, history_metadata, apim_request_id):
    response_obj = {
        "id": chatCompletion.id,
        "model": chatCompletion.model,
        "created": chatCompletion.created,
        "object": chatCompletion.object,
        "choices": [{"messages": []}],
        "history_metadata": history_metadata,
        "apim-request-id": apim_request_id,
    }

    if len(chatCompletion.choices) > 0:
        message = chatCompletion.choices[0].message
        if message:
            if hasattr(message, "context"):
                response_obj["choices"][0]["messages"].append(
                    {
                        "role": "tool",
                        "content": json.dumps(message.context),
                    }
                )
            response_obj["choices"][0]["messages"].append(
                {
                    "role": "assistant",
                    "content": message.content,
                }
            )
            return response_obj

    return {}

def format_stream_response(chatCompletionChunk, history_metadata, apim_request_id):
    response_obj = {
        "id": chatCompletionChunk.id,
        "model": chatCompletionChunk.model,
        "created": chatCompletionChunk.created,
        "object": chatCompletionChunk.object,
        "choices": [{"messages": []}],
        "history_metadata": history_metadata,
        "apim-request-id": apim_request_id,
    }

    if len(chatCompletionChunk.choices) > 0:
        delta = chatCompletionChunk.choices[0].delta
        if delta:
            if hasattr(delta, "context"):
                messageObj = {"role": "tool", "content": json.dumps(delta.context)}
                response_obj["choices"][0]["messages"].append(messageObj)
                return response_obj
            if delta.role == "assistant" and hasattr(delta, "context"):
                messageObj = {
                    "role": "assistant",
                    "context": delta.context,
                }
                response_obj["choices"][0]["messages"].append(messageObj)
                return response_obj
            else:
                if delta.content:
                    messageObj = {
                        "role": "assistant",
                        "content": delta.content,
                    }
                    response_obj["choices"][0]["messages"].append(messageObj)
                    return response_obj

    return {}


def format_pf_non_streaming_response(
    chatCompletion, history_metadata, response_field_name, citations_field_name, message_uuid=None
):
    if chatCompletion is None:
        logging.error(
            "chatCompletion object is None - Increase PROMPTFLOW_RESPONSE_TIMEOUT parameter"
        )
        return {
            "error": "No response received from promptflow endpoint increase PROMPTFLOW_RESPONSE_TIMEOUT parameter or check the promptflow endpoint."
        }
    if "error" in chatCompletion:
        logging.error(f"Error in promptflow response api: {chatCompletion['error']}")
        return {"error": chatCompletion["error"]}

    logging.debug(f"chatCompletion: {chatCompletion}")
    try:
        messages = []
        if response_field_name in chatCompletion:
            messages.append({
                "role": "assistant",
                "content": chatCompletion[response_field_name] 
            })
        if citations_field_name in chatCompletion:
            messages.append({ 
                "role": "tool",
                "content": chatCompletion[citations_field_name]
                #"content":"{\"citations\": [{\"content\": \"best practices and\\nguidance to distribute and enroll existing\\ncustomers to use their app.\\n\\nReal-time alerts when a consumer:\\nSelf-selects as Ready to Buy\\nAchieves 4 stars in Readiness\\nCredit score increases one tier (e.g. poor to\\nfair)\\nSets a monthly payment goal\\nSearches for a property (also can alert the real\\nestate agent)\\nSaves at least one property*\\n\\nEmails that inform clients and their loans\\nofficers on the enhancements to the FinLocker\\nplatform.\\n\\nFinLocker Customer Academy workshops.\\n\\nLive demos of platform enhancements.\\n\\nThought-leadership papers and guides with\\nmarket trends and practical advice to build\\nbusiness with consumer and referral partners\\nusing their branded FinLocker platform.\\n\\n      *roadmap\\n\\n  How we add value:\\n\\nROI positive solution for mortgage\\noriginators to generate and nurture their\\ndatabase.\\n\\nPlug n play marketing collateral \\u2013 social\\nmedia posts, videos, enrollment emails,\\nlanding pages - to promote the app and\\nreach, assist  and engage consumers.\\n\\nFinLocker is aligned to the business goals of\\nour clients during the sales process and\\nthroughout onboarding.\\n\\nCo-branding of app with real estate agent(s)\\nto build their database and strengthen their\\nagent relationships.\\n\\nAdmin portal provides visibility into:\\nSummary of all active consumer apps\\nRecent consumer activity\\nCredit score band of each consumer\\nConsumers who have recently improved\\ntheir credit scores\\nHomeownership objectives of their\\nconsumers\\nReadiness star distribution of their\\nconsumers\\nProperty value and search related activity\\n\\nAPIs for connectivity to enterprise CRM.\\n\\nIntegrations with Total Expert and Shape\\nSoftware CRM.\\n\\nMortgage Originators seek a Cost-effective Competitive Edge to Connect Up-the-funnel with Homebuyers\", \"title\": \"FinLocker-Consumer-Client-Value-Flyer.pdf\", \"url\": null, \"filepath\": null, \"chunk_id\": \"0\"}, {\"content\": \"needs to\\ninform our product roadmap. Assisting our\\nclients\\u2019 consumers on their journey to\\nhomeownership is a success for us.\\n\\nInventory and Affordability Challenges have Extended the Home Buying Readiness Journey\\n\\n\\n\\n  What our clients need:\\n\\nLead nurturing: A solution to slow the\\nleakage from their lead database for:\\n\\nRenters &amp; dreamers (18+ months out\\nfrom buying a home)\\nProspective homebuyers (3-18 months\\nfrom buying a home)\\nHomeowners (existing borrowers and\\nfuture refinance and purchase\\ntransactions)\\n\\nOrganic lead generation: Lead magnet\\nand call-to-action on their social media\\nand other direct to consumer marketing\\nto attract prospective homebuyers to\\ntheir business.\\n\\nRecover turn down applicants:        Re-\\nengage and nurture turned down\\napplicants to overcome the financial\\nreasons their mortgage application was\\ndenied.\\n\\nCreate customers for life: A platform to\\nstay meaningfully connected with\\nhomeowners after closing so they\\u2019ll stay\\ntop-of-mind for the next home-related\\nopportunity. \\n\\nA safe and secure consumer\\nengagement platform that will not sell\\nthe personal information or financial\\ndata of their consumers to their\\ncompetition or cause credit triggers.\\n\\n  How we engage them:\\n\\nThe assigned Customer Success Manager\\nregularly meets with their clients to provide\\noverall team and user analytics, address any\\nconcerns, listen to their suggestions, and advise\\nhow the FinLocker platform can help solve their\\nbusiness goals.\\n\\nLO Playbooks provide best practices and\\nguidance to distribute and enroll existing\\ncustomers to use their app.\\n\\nReal-time alerts when a consumer:\\nSelf-selects as Ready to Buy\\nAchieves 4 stars in Readiness\\nCredit score increases one tier (e.g. poor to\\nfair)\\nSets a monthly payment goal\\nSearches for a property (also can alert the real\\nestate agent)\\nSaves at least one property*\\n\\nEmails that inform clients and their loans\\nofficers on the enhancements to the FinLocker\\nplatform.\\n\\nFinLocker Customer Academy workshops.\", \"title\": \"FinLocker-Consumer-Client-Value-Flyer.pdf\", \"url\": null, \"filepath\": null, \"chunk_id\": \"0\"}, {\"content\": \"I\\u2019m ready for the next step\\nI\\u2019m not currently looking (homeowner)\\n\\nJourneys that guide them to accomplish\\nthe homeownership goals they selected\\nduring account creation:\\n\\nFind the right home for my budget\\nLearn about the right mortgage for me\\nImprove my finances to get approved\\nSave up for a home-related goal\\nGrow my household wealth\\nBe a savvy homeowner\\n\\nEmail / push notifications:\\nCredit score increase / decrease \\nCredit alert placed on credit report\\nCredit streak achieve\\nProperty value update\\nReadiness streak achieved\\nRe-engage inactive users after 3 months\\n\\n  How we add value:\\n\\nWe put consumers in control of their\\nfinancial wellbeing with tools to:\\n\\nBuild and monitor their credit \\nManage their financial accounts and\\nspending\\nCreate goals and budgets to save for a down\\npayment and closing costs, pay down debt,\\nachieve financial goals\\nTrack their progress toward mortgage\\nreadiness\\nOvercome their financial challenges to\\nachieve mortgage eligibility with\\npersonalized action plan\\nSearch and save properties\\nTrack home value and home equity\\nEducational resources to improve their\\nfinancial literacy and knowledge of the\\nmortgage process\\nContact their loan officer and share the\\nresults of the Readiness assessment to get\\npre-qualified\\nSecurely save financial documents and share\\nfinancial data with their loan officer for a pre-\\nqualification and mortgage application\\n\\nWhile our business model is B2B2C, we put\\nthe consumer first. We regularly interview\\nconsumers to understand their needs to\\ninform our product roadmap. Assisting our\\nclients\\u2019 consumers on their journey to\\nhomeownership is a success for us.\\n\\nInventory and Affordability Challenges have Extended the Home Buying Readiness Journey\\n\\n\\n\\n  What our clients need:\\n\\nLead nurturing: A solution to slow the\\nleakage from their lead database for:\\n\\nRenters &amp; dreamers (18+ months out\\nfrom buying a home)\\nProspective homebuyers (3-18 months\\nfrom buying a home)\\nHomeowners (existing borrowers and\\nfuture refinance and purchase\", \"title\": \"FinLocker-Consumer-Client-Value-Flyer.pdf\", \"url\": null, \"filepath\": null, \"chunk_id\": \"0\"}, {\"content\": \"W hat consumers need and desire:\\n\\nEmpowerment Through Knowledge: \\nEquipped with tools and insights to navigate   \\nthe complexities of financial planning with\\nconfidence. Empowered to take control of\\ntheir financial and emotional journey towards\\nhomeownership.\\n\\nPersonalized Support and Encouragement: \\nReceive personalized guidance that\\nacknowledges their unique financial\\nchallenges. Feel supported and encouraged\\nto overcome hurdles that stand between their\\ndream of homeownership.\\n\\nClarity and confidence in the home-\\nbuying process: Understand each step of\\nthe mortgage process with clarity,\\ntransforming what can be an\\noverwhelming experience into an exciting\\nmilestone. Feel confident as they move\\ncloser to making homeownership a reality.\\n\\nTrust and security in making financial\\ndecisions: Enjoy peace of mind knowing\\ntheir personal and financial information is\\nheld in strict confidence, with a guarantee\\nof bank-level data security and privacy.\\nTrust that their journey to homeownership\\nis protected and supported every step of\\nthe way.\\n\\n  How we educate and engage them:\\n\\nPersona-based journeys power the app to\\nperpetually assess where users are on their\\nhomeownership journey. Automation within\\nthe system guides them with data-driven\\ndynamic action plans.\\n\\nDigital personal finance tools to help them\\nachieve their homeownership goals and\\nobjectives, based on persona:\\n\\nI\\u2019m just getting started\\nI\\u2019m ready to qualify for a mortgage\\nI hit a challenge and need help\\nI\\u2019m ready for the next step\\nI\\u2019m not currently looking (homeowner)\\n\\nJourneys that guide them to accomplish\\nthe homeownership goals they selected\\nduring account creation:\\n\\nFind the right home for my budget\\nLearn about the right mortgage for me\\nImprove my finances to get approved\\nSave up for a home-related goal\\nGrow my household wealth\\nBe a savvy homeowner\\n\\nEmail / push notifications:\\nCredit score increase / decrease \\nCredit alert placed on credit report\\nCredit streak achieve\\nProperty value update\", \"title\": \"FinLocker-Consumer-Client-Value-Flyer.pdf\", \"url\": null, \"filepath\": null, \"chunk_id\": \"0\"}]}"
                #"content": "{\"citations\": [{\"content\": \"your FinLocker\\n· Activities to avoid between mortgage pre-approval and closing on your new home – reference our blog\\n· How to start a mortgage application with your FinLocker or digital mortgage application\\n· Mortgage loan process after an application has been submitted\\n· What to do if your home loan is denied \\n· Closing process\\n· Obtaining homeowners insurance – reference our blog Types of Homeowners Insurance, What It Does and Doesn’t Cover\\n· What does escrow cover?\\n\\nShopping for a Home \\n· How to select a home and neighborhood – reference our blog 6 Tips to Improve the Effectiveness of Your Online Home Search\\n· Evaluating HOA fees\\n· Online home tours vs. in-person open houses\\n· How to make a competitive offer \\n· Negotiating tips \\n· Purchase contract \\n· Home inspections\\n\\nSustaining Homeownership\\n· How to file for homestead exemption in your state – if applicable – reference our blog\\n· Using your FinLocker to track their mortgage account, home equity and property value\\n\\nMarketing your first-time homebuyer workshop\\n· Co-host the workshop or webinar series with a real estate agent to cover the whole home buying process. \\nYou’ll double your marketing outreach to attract attendees. The workshop or webinar series can be promoted via each presenter’s social media channels. Offer your FinLocker as an incentive to everyone who attends or registers for the workshop.\\n· Record the presentation and send the on-demand link to attendees to rewatch the seminar with an invitation to create a FinLocker as a \"thank you for attending\"\\n·\"}, {\"content\": \"b\"}, {\"content\": \"c\"}, {\"content\": \"d\"}, {\"content\": \"e\"}]}"

            })
        
        
        response_obj = {
            "id": chatCompletion["id"],
            "model": "",
            "created": "",
            "object": "",
            "choices": [
                {
                    "messages": messages
                }
            ],
            "history_metadata": history_metadata
        }
        return response_obj
    except Exception as e:
        logging.error(f"Exception in format_pf_non_streaming_response: {e}")
        return {}


def convert_to_pf_format(input_json, request_field_name, response_field_name):
    output_json = []
    logging.debug(f"Input json: {input_json}")
    # align the input json to the format expected by promptflow chat flow
    for message in input_json["messages"]:
        if message:
            if message["role"] == "user":
                new_obj = {
                    "inputs": {request_field_name: message["content"]},
                    "outputs": {response_field_name: ""},
                }
                output_json.append(new_obj)
            elif message["role"] == "assistant" and len(output_json) > 0:
                output_json[-1]["outputs"][response_field_name] = message["content"]
    logging.debug(f"PF formatted response: {output_json}")
    return output_json


def comma_separated_string_to_list(s: str) -> List[str]:
    '''
    Split comma-separated values into a list.
    '''
    return s.strip().replace(' ', '').split(',')

