import os
from typing import List, Optional
import requests
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

# Initialize FastAPI App
app = FastAPI(
    title="Media Tracker API",
    description="API for searching TV shows/movies, streaming platforms, IMDb ratings, and next episode dates.",
    version="1.0.0",
)

# Fetch API Key from Environment Variables (Recommended) or fallback to hardcoded
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "YOUR_TMDB_API_KEY")
BASE_URL = "https://api.themoviedb.org/3"


# --- Data Models ---
class SearchResult(BaseModel):
    id: int
    title: str
    media_type: str
    year: str


class MediaSummary(BaseModel):
    title: str
    media_type: str
    plot: str
    rating: str
    imdb_link: str
    streaming_on: List[str]
    total_seasons: Optional[int] = None
    total_episodes: Optional[int] = None
    most_recent_episode: Optional[str] = None


class EpisodeTrackerResponse(BaseModel):
    show_id: int
    show_name: str
    status: str
    message: str


# --- Helper Functions ---
def fetch_tmdb(endpoint: str, params: dict):
    params["api_key"] = TMDB_API_KEY
    response = requests.get(f"{BASE_URL}/{endpoint}", params=params)
    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"TMDb API Error: {response.json().get('status_message', 'Failed to fetch data')}",
        )
    return response.json()


# --- API Endpoints ---


@app.get("/", summary="Root Endpoint")
def read_root():
    return {
        "message": "Welcome to the Media Tracker API! Visit /docs for interactive documentation."
    }


@app.get(
    "/search", response_model=List[SearchResult], summary="Search Movies & TV Shows"
)
def search(query: str = Query(..., description="Movie or TV Show title to search")):
    """Search for movies and TV shows matching a title string."""
    data = fetch_tmdb("search/multi", {"query": query})
    results = []

    for item in data.get("results", []):
        media_type = item.get("media_type")
        if media_type in ["movie", "tv"]:
            title = (
                item.get("title") if media_type == "movie" else item.get("name")
            )
            release_date = (
                item.get("release_date")
                if media_type == "movie"
                else item.get("first_air_date", "")
            )
            year = release_date[:4] if release_date else "N/A"

            results.append(
                SearchResult(
                    id=item["id"],
                    title=title,
                    media_type=media_type,
                    year=year,
                )
            )
    return results


@app.get(
    "/summary/{media_type}/{media_id}",
    response_model=MediaSummary,
    summary="Get Media Summary",
)
def get_summary(
    media_type: str,
    media_id: int,
    region: str = Query("US", description="Two-letter country code (e.g., US, GB, CA)"),
):
    """Retrieve detailed overview, rating, streaming options, and episode info."""
    if media_type not in ["movie", "tv"]:
        raise HTTPException(
            status_code=400, detail="media_type must be either 'movie' or 'tv'"
        )

    # Fetch main details along with external IDs and watch providers
    details = fetch_tmdb(
        f"{media_type}/{media_id}",
        {"append_to_response": "external_ids,watch/providers"},
    )

    # Ratings & External Links
    vote_avg = details.get("vote_average")
    rating_str = f"{vote_avg:.1f}/10 (TMDb)" if vote_avg else "N/A"
    imdb_id = details.get("external_ids", {}).get("imdb_id")
    imdb_link = f"https://www.imdb.com/title/{imdb_id}/" if imdb_id else "N/A"

    # Streaming Platforms
    provider_data = (
        details.get("watch/providers", {}).get("results", {}).get(region, {})
    )
    flatrate = provider_data.get("flatrate", [])
    platforms = [p["provider_name"] for p in flatrate] if flatrate else ["None (Check Rent/Buy)"]

    # Base Summary
    summary = {
        "title": details.get("title") if media_type == "movie" else details.get("name"),
        "media_type": media_type.upper(),
        "plot": details.get("overview") or "No plot overview available.",
        "rating": rating_str,
        "imdb_link": imdb_link,
        "streaming_on": platforms,
    }

    # TV Specific Fields
    if media_type == "tv":
        summary["total_seasons"] = details.get("number_of_seasons")
        summary["total_episodes"] = details.get("number_of_episodes")

        last_ep = details.get("last_episode_to_air")
        if last_ep:
            summary["most_recent_episode"] = (
                f"S{last_ep.get('season_number')}E{last_ep.get('episode_number')} "
                f"- '{last_ep.get('name')}' (Aired: {last_ep.get('air_date')})"
            )

    return summary


@app.get(
    "/next-episode/{tv_id}",
    response_model=EpisodeTrackerResponse,
    summary="Track Next/Final Episode",
)
def next_episode(tv_id: int):
    """Check air date for upcoming episode or retrieve final air date if completed."""
    details = fetch_tmdb(f"tv/{tv_id}", {})

    show_name = details.get("name", "Unknown Show")
    status = details.get("status", "Unknown")
    next_ep = details.get("next_episode_to_air")
    last_ep = details.get("last_episode_to_air")

    if next_ep:
        msg = (
            f"Next episode (S{next_ep.get('season_number')}E{next_ep.get('episode_number')}) "
            f"is scheduled to air on {next_ep.get('air_date')}."
        )
    elif status in ["Ended", "Canceled"]:
        last_date = last_ep.get("air_date") if last_ep else "Unknown"
        msg = f"Series has {status.lower()}. The final episode aired on {last_date}."
    else:
        msg = "Currently in production or on hiatus. Next episode date is unannounced."

    return EpisodeTrackerResponse(
        show_id=tv_id, show_name=show_name, status=status, message=msg
    )
