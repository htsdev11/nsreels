from math import ceil
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework import status


DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 10


class CustomPagination(PageNumberPagination):
    page_size = DEFAULT_PAGE_SIZE
    page_size_query_param = "page_size"
    max_page_size = 100

    def get_paginated_response(self, data):
        current_page = int(
            self.request.GET.get("page", DEFAULT_PAGE)
        )

        current_page_size = int(
            self.request.GET.get(
                "page_size",
                self.page_size
            )
        )

        total_items = self.page.paginator.count
        total_pages = ceil(total_items / current_page_size)

        return Response({
            "success": True,
            "pagination": {
                "count": total_items,
                "page": current_page,
                "pages": total_pages,
                "page_size": current_page_size,
                "next": self.get_next_link(),
                "previous": self.get_previous_link(),
            },
            "results": data
        }, status=status.HTTP_200_OK)

    def get_failure_response(self, message, response_status):
        return Response({
            "success": False,
            "message": message,
            "pagination": None,
            "results": []
        }, status=response_status)