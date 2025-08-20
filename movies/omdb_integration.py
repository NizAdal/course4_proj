import logging
import re
from datetime import timedelta

from django.utils.timezone import now
from movies.models import Genre, SearchTerm, Movie

import omdb  # ✅ Replaces omdb.django_client
omdb.set_default('apikey', 'your_omdb_api_key_here')  # 🔑 Set your OMDb API key here

logger = logging.getLogger(__name__)

def get_or_create_genres(genre_names):
    for genre_name in genre_names:
        genre, created = Genre.objects.get_or_create(name=genre_name)
        yield genre

def fill_movie_details(movie):
    """
    Fetch a movie's full details from OMDb. Then, save it to the DB. If the movie already has a `full_record` this does
    nothing, so it's safe to call with any `Movie`.
    """
    if movie.is_full_record:
        logger.warning("'%s' is already a full record.", movie.title)
        return

    movie_details = omdb.imdbid(movie.imdb_id)  # 🔄 Replaces get_client_from_settings().get_by_imdb_id()

    if not movie_details:
        logger.error("No details found for IMDb ID: %s", movie.imdb_id)
        return

    movie.title = movie_details.get('Title')
    movie.year = movie_details.get('Year')
    movie.plot = movie_details.get('Plot')

    runtime = movie_details.get('Runtime', '0 min')
    try:
        movie.runtime_minutes = int(runtime.split()[0])
    except ValueError:
        movie.runtime_minutes = None

    movie.genres.clear()
    for genre in get_or_create_genres(movie_details.get('Genre', '').split(', ')):
        movie.genres.add(genre)

    movie.is_full_record = True
    movie.save()

def search_and_save(search):
    """
    Perform a search for search_term against the API, but only if it hasn't been searched in the past 24 hours. Save
    each result to the local DB as a partial record.
    """
    normalized_search_term = re.sub(r"\s+", " ", search.lower())
    search_term, created = SearchTerm.objects.get_or_create(term=normalized_search_term)

    if not created and (search_term.last_search > now() - timedelta(days=1)):
        logger.warning("Search for '%s' was performed in the past 24 hours so not searching again.", normalized_search_term)
        return

    results = omdb.search(search)  # 🔄 Replaces omdb_client.search()

    if not results:
        logger.warning("No results found for search term: '%s'", search)
        return

    for omdb_movie in results:
        imdb_id = omdb_movie.get('imdbID')
        title = omdb_movie.get('Title')
        year = omdb_movie.get('Year')

        if not imdb_id:
            continue

        logger.info("Saving movie: '%s' / '%s'", title, imdb_id)
        movie, created = Movie.objects.get_or_create(
            imdb_id=imdb_id,
            defaults={
                "title": title,
                "year": year,
            },
        )

        if created:
            logger.info("Movie created: '%s'", movie.title)

    search_term.last_search = now()
    search_term.save()
