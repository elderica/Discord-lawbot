import io
from urllib.parse import urljoin
import httpx
import jq

API_ENDPOINT_LAWS = "https://laws.e-gov.go.jp/api/2/laws"

async def title(law_title: str):
    jq_query = '''
    .laws | map({ law_num: .law_info.law_num,
                law_title: .current_revision_info.law_title,
                law_revision_id: .current_revision_info.law_revision_id})
    '''
    async with httpx.AsyncClient() as client:
        params = { 'law_title': law_title }
        response = await client.get(API_ENDPOINT_LAWS, params=params)
        return jq.compile(jq_query).input_text(response.text).first()

API_ENDPOINT_LAW_DATA = 'https://laws.e-gov.go.jp/api/2/law_data/'

async def text(law_id_or_num_or_revision_id: str):
    jq_query = '''
    .law_full_text.children[] |
    select(.tag=="LawBody") |
    recurse(.children[]?; type=="object") |
    select(.tag=="Sentence") | .children[]
    '''
    url = urljoin(API_ENDPOINT_LAW_DATA, law_id_or_num_or_revision_id)
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        if response.status_code == httpx.codes.OK:
            return jq.compile(jq_query).input_text(response.text).all()
        else:
            return None

if __name__ == '__main__':
    import sys
    import asyncio
    results = asyncio.run(title(sys.argv[1]))
    with io.StringIO() as table:
        print("|law_num|law_revision_id|law_title|", file=table)
        print("|:------|:--------------|:--------|", file=table)
        for l in results:
            print(f"|{l['law_num']}|{l['law_revision_id']}|{l['law_title']}|", file=table)
        print(table.getvalue())
